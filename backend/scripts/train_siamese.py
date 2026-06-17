import os
import sys
import argparse
import numpy as np
import torch
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from typing import List, Tuple, Dict, Optional
from pathlib import Path
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.siamese_model import VoiceprintSiameseModel, TripletLoss, OnlineTripletMining
from app.services.feature_normalizer import AdaptiveNormalizer
from app.core.config import settings


class VoiceprintDataset(Dataset):
    def __init__(self, features: List[np.ndarray], labels: List[int],
                 augment: bool = True, n_augment: int = 5):
        self.features = features
        self.labels = labels
        self.augment = augment
        self.n_augment = n_augment
        self._build_index()

    def _build_index(self):
        self.label_to_indices: Dict[int, List[int]] = {}
        for idx, label in enumerate(self.labels):
            if label not in self.label_to_indices:
                self.label_to_indices[label] = []
            self.label_to_indices[label].append(idx)

        self.valid_labels = [
            label for label, indices in self.label_to_indices.items()
            if len(indices) >= 2
        ]

    def _augment_feature(self, feature: np.ndarray) -> np.ndarray:
        augmented = feature.copy()
        aug_type = np.random.choice(['none', 'noise', 'scale', 'shift', 'mask', 'mix'])

        if aug_type == 'noise':
            noise_level = np.random.uniform(0.01, 0.08)
            noise = np.random.randn(len(augmented)) * noise_level
            augmented = augmented + noise

        elif aug_type == 'scale':
            scale_factor = np.random.uniform(0.85, 1.15)
            augmented = augmented * scale_factor

        elif aug_type == 'shift':
            shift_amount = int(np.random.uniform(-5, 5))
            augmented = np.roll(augmented, shift_amount)

        elif aug_type == 'mask':
            mask_ratio = np.random.uniform(0.05, 0.15)
            n_mask = int(len(augmented) * mask_ratio)
            mask_indices = np.random.choice(len(augmented), n_mask, replace=False)
            augmented[mask_indices] = 0

        elif aug_type == 'mix':
            noise = np.random.randn(len(augmented)) * np.random.uniform(0.01, 0.05)
            scale = np.random.uniform(0.9, 1.1)
            augmented = (augmented + noise) * scale

        norm = np.linalg.norm(augmented) + 1e-10
        augmented = augmented / norm

        return augmented

    def __len__(self):
        if self.augment:
            return len(self.features) * self.n_augment
        return len(self.features)

    def __getitem__(self, idx):
        if self.augment:
            original_idx = idx // self.n_augment
            feature = self.features[original_idx]
            label = self.labels[original_idx]
            feature = self._augment_feature(feature)
        else:
            feature = self.features[idx]
            label = self.labels[idx]

        return (
            torch.tensor(feature, dtype=torch.float32),
            torch.tensor(label, dtype=torch.long)
        )


class SyntheticDataGenerator:
    def __init__(self, feature_dim: int = 200, n_classes: int = 50,
                 n_samples_per_class: int = 10):
        self.feature_dim = feature_dim
        self.n_classes = n_classes
        self.n_samples_per_class = n_samples_per_class

    def generate(self) -> Tuple[List[np.ndarray], List[int]]:
        features = []
        labels = []

        for class_idx in range(self.n_classes):
            class_mean = np.random.randn(self.feature_dim) * 0.5
            class_mean = class_mean / (np.linalg.norm(class_mean) + 1e-10)

            for sample_idx in range(self.n_samples_per_class):
                variation = np.random.randn(self.feature_dim) * np.random.uniform(0.1, 0.3)
                feature = class_mean + variation

                warp_strength = np.random.uniform(0, 0.15)
                n_warp_points = max(2, int(self.feature_dim * warp_strength))
                for _ in range(n_warp_points):
                    start = np.random.randint(0, self.feature_dim - 10)
                    length = np.random.randint(5, 20)
                    factor = np.random.uniform(0.9, 1.1)
                    feature[start:start + length] *= factor

                if np.random.random() < 0.5:
                    noise = np.random.randn(self.feature_dim) * np.random.uniform(0.02, 0.1)
                    feature = feature + noise

                feature = feature / (np.linalg.norm(feature) + 1e-10)

                features.append(feature)
                labels.append(class_idx)

        return features, labels

    def generate_mic_variations(self, base_features: List[np.ndarray],
                                base_labels: List[int],
                                n_mic_variations: int = 3) -> Tuple[List[np.ndarray], List[int]]:
        all_features = []
        all_labels = []

        mic_responses = [
            (1.0, 0.0),
            (0.9, 0.05),
            (1.1, 0.02),
            (0.85, 0.08),
        ]

        for feat, label in zip(base_features, base_labels):
            all_features.append(feat)
            all_labels.append(label)

            for mic_idx in range(min(n_mic_variations, len(mic_responses))):
                scale, noise = mic_responses[mic_idx]
                mic_feature = feat * scale + np.random.randn(len(feat)) * noise
                mic_feature = mic_feature / (np.linalg.norm(mic_feature) + 1e-10)
                all_features.append(mic_feature)
                all_labels.append(label)

        return all_features, all_labels


def train_model(output_path: str,
                feature_dim: int = 200,
                embedding_dim: int = 128,
                n_classes: int = 100,
                n_samples_per_class: int = 15,
                batch_size: int = 64,
                n_epochs: int = 100,
                learning_rate: float = 0.001,
                margin: float = 0.5,
                device: Optional[str] = None):
    print("=" * 60)
    print("Voiceprint Siamese Network Training")
    print("=" * 60)
    print(f"Feature dim: {feature_dim}")
    print(f"Embedding dim: {embedding_dim}")
    print(f"Classes: {n_classes}")
    print(f"Samples per class: {n_samples_per_class}")
    print(f"Batch size: {batch_size}")
    print(f"Epochs: {n_epochs}")
    print(f"Learning rate: {learning_rate}")
    print(f"Margin: {margin}")
    print()

    print("Generating synthetic training data...")
    generator = SyntheticDataGenerator(
        feature_dim=feature_dim,
        n_classes=n_classes,
        n_samples_per_class=n_samples_per_class
    )
    features, labels = generator.generate()
    features, labels = generator.generate_mic_variations(features, labels)

    print(f"Total training samples: {len(features)}")
    print(f"Unique classes: {len(set(labels))}")

    print("\nApplying adaptive normalization...")
    normalizer = AdaptiveNormalizer(feature_dim=feature_dim)
    features = [normalizer.normalize(f) for f in features]

    train_size = int(0.85 * len(features))
    indices = np.random.permutation(len(features))
    train_indices = indices[:train_size]
    val_indices = indices[train_size:]

    train_features = [features[i] for i in train_indices]
    train_labels = [labels[i] for i in train_indices]
    val_features = [features[i] for i in val_indices]
    val_labels = [labels[i] for i in val_indices]

    print(f"Train samples: {len(train_features)}")
    print(f"Val samples: {len(val_features)}")

    train_dataset = VoiceprintDataset(
        train_features, train_labels, augment=True, n_augment=4
    )
    val_dataset = VoiceprintDataset(
        val_features, val_labels, augment=False
    )

    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=batch_size, shuffle=False, num_workers=0
    )

    print("\nInitializing model...")
    model_wrapper = VoiceprintSiameseModel(
        input_dim=feature_dim,
        embedding_dim=embedding_dim,
        margin=margin,
        device=device
    )
    model = model_wrapper.model
    triplet_loss_fn = TripletLoss(margin=margin, distance_metric='cosine')
    triplet_miner = OnlineTripletMining(margin=margin, distance_metric='cosine')

    optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=5, verbose=True
    )

    best_val_loss = float('inf')
    patience_counter = 0
    early_stopping_patience = 15

    print("\nStarting training...")
    print("-" * 60)

    for epoch in range(n_epochs):
        model.train()
        total_loss = 0
        n_batches = 0
        n_valid_triplets = 0

        for batch_idx, (features_batch, labels_batch) in enumerate(train_loader):
            features_batch = features_batch.to(model_wrapper.device)
            labels_batch = labels_batch.to(model_wrapper.device)

            optimizer.zero_grad()

            embeddings = model.forward_once(features_batch)

            anchors, positives, negatives = triplet_miner.get_triplets(
                embeddings, labels_batch
            )

            if anchors is None:
                continue

            loss = triplet_loss_fn(anchors, positives, negatives)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1
            n_valid_triplets += len(anchors)

        avg_train_loss = total_loss / max(n_batches, 1)

        model.eval()
        val_loss = 0
        val_batches = 0
        with torch.no_grad():
            for features_batch, labels_batch in val_loader:
                features_batch = features_batch.to(model_wrapper.device)
                labels_batch = labels_batch.to(model_wrapper.device)

                embeddings = model.forward_once(features_batch)
                anchors, positives, negatives = triplet_miner.get_triplets(
                    embeddings, labels_batch
                )

                if anchors is not None:
                    loss = triplet_loss_fn(anchors, positives, negatives)
                    val_loss += loss.item()
                    val_batches += 1

        avg_val_loss = val_loss / max(val_batches, 1)

        print(f"Epoch {epoch + 1:3d}/{n_epochs} | "
              f"Train Loss: {avg_train_loss:.4f} | "
              f"Val Loss: {avg_val_loss:.4f} | "
              f"Valid Triplets: {n_valid_triplets} | "
              f"LR: {optimizer.param_groups[0]['lr']:.6f}")

        scheduler.step(avg_val_loss)

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            patience_counter = 0
            model_wrapper.save(output_path)
            print(f"  -> Saved best model (val_loss: {best_val_loss:.4f})")
        else:
            patience_counter += 1

        if patience_counter >= early_stopping_patience:
            print(f"\nEarly stopping at epoch {epoch + 1}")
            break

    print("\n" + "=" * 60)
    print(f"Training complete! Best validation loss: {best_val_loss:.4f}")
    print(f"Model saved to: {output_path}")
    print("=" * 60)

    return model_wrapper


def generate_pretrained_model(model_dir: str = "backend/models"):
    os.makedirs(model_dir, exist_ok=True)

    model_path = os.path.join(model_dir, "voiceprint_siamese.pt")
    normalizer_path = os.path.join(model_dir, "normalizer.pkl")

    model_wrapper = train_model(
        output_path=model_path,
        feature_dim=200,
        embedding_dim=128,
        n_classes=100,
        n_samples_per_class=15,
        batch_size=64,
        n_epochs=100,
        learning_rate=0.001,
        margin=0.5,
    )

    normalizer = AdaptiveNormalizer(feature_dim=200)
    with open(normalizer_path, 'wb') as f:
        pickle.dump(normalizer, f)

    print(f"\nNormalizer saved to: {normalizer_path}")

    return model_wrapper, normalizer


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Train voiceprint Siamese network')
    parser.add_argument('--output', '-o', type=str,
                        default='backend/models/voiceprint_siamese.pt',
                        help='Output model path')
    parser.add_argument('--feature-dim', type=int, default=200,
                        help='Input feature dimension')
    parser.add_argument('--embedding-dim', type=int, default=128,
                        help='Embedding dimension')
    parser.add_argument('--epochs', type=int, default=100,
                        help='Number of training epochs')
    parser.add_argument('--batch-size', type=int, default=64,
                        help='Batch size')
    parser.add_argument('--lr', type=float, default=0.001,
                        help='Learning rate')
    parser.add_argument('--margin', type=float, default=0.5,
                        help='Triplet loss margin')
    parser.add_argument('--device', type=str, default=None,
                        help='Device (cpu/cuda)')

    args = parser.parse_args()

    model_dir = os.path.dirname(args.output)
    os.makedirs(model_dir, exist_ok=True)

    train_model(
        output_path=args.output,
        feature_dim=args.feature_dim,
        embedding_dim=args.embedding_dim,
        n_epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        margin=args.margin,
        device=args.device,
    )
