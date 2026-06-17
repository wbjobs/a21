import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple, Optional


class SiameseEmbeddingNet(nn.Module):
    def __init__(self, input_dim: int = 200, embedding_dim: int = 128, dropout: float = 0.3):
        super(SiameseEmbeddingNet, self).__init__()

        self.input_dim = input_dim
        self.embedding_dim = embedding_dim

        self.network = nn.Sequential(
            nn.Linear(input_dim, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(dropout),

            nn.Linear(512, 384),
            nn.BatchNorm1d(384),
            nn.ReLU(),
            nn.Dropout(dropout),

            nn.Linear(384, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(dropout),

            nn.Linear(256, embedding_dim),
        )

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm1d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward_once(self, x: torch.Tensor) -> torch.Tensor:
        embedding = self.network(x)
        embedding = F.normalize(embedding, p=2, dim=1)
        return embedding

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        embed1 = self.forward_once(x1)
        embed2 = self.forward_once(x2)
        return embed1, embed2

    def get_embedding(self, x: torch.Tensor) -> torch.Tensor:
        if len(x.shape) == 1:
            x = x.unsqueeze(0)
        with torch.no_grad():
            return self.forward_once(x).squeeze(0)


class TripletLoss(nn.Module):
    def __init__(self, margin: float = 1.0, distance_metric: str = 'cosine'):
        super(TripletLoss, self).__init__()
        self.margin = margin
        self.distance_metric = distance_metric

    def compute_distance(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        if self.distance_metric == 'cosine':
            return 1 - F.cosine_similarity(x1, x2, dim=1)
        elif self.distance_metric == 'euclidean':
            return F.pairwise_distance(x1, x2, p=2)
        else:
            raise ValueError(f"Unknown distance metric: {self.distance_metric}")

    def forward(self, anchor: torch.Tensor, positive: torch.Tensor,
                negative: torch.Tensor) -> torch.Tensor:
        positive_dist = self.compute_distance(anchor, positive)
        negative_dist = self.compute_distance(anchor, negative)

        losses = F.relu(positive_dist - negative_dist + self.margin)

        hard_triplets = losses > 1e-16
        if hard_triplets.any():
            losses = losses[hard_triplets]

        return losses.mean() if losses.numel() > 0 else torch.tensor(0.0)


class OnlineTripletMining:
    def __init__(self, margin: float = 1.0, distance_metric: str = 'cosine'):
        self.margin = margin
        self.distance_metric = distance_metric
        self.triplet_loss = TripletLoss(margin=margin, distance_metric=distance_metric)

    def compute_distance_matrix(self, embeddings: torch.Tensor) -> torch.Tensor:
        if self.distance_metric == 'cosine':
            similarity = embeddings @ embeddings.T
            distance = 1 - similarity
        else:
            diff = embeddings.unsqueeze(1) - embeddings.unsqueeze(0)
            distance = torch.sqrt((diff ** 2).sum(dim=2))
        return distance

    def get_triplets(self, embeddings: torch.Tensor, labels: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        distance_matrix = self.compute_distance_matrix(embeddings)
        labels = labels.cpu().numpy()

        anchors, positives, negatives = [], [], []

        unique_labels = set(labels)
        for anchor_idx, label in enumerate(labels):
            same_label_indices = np.where(labels == label)[0]
            diff_label_indices = np.where(labels != label)[0]

            if len(same_label_indices) < 2 or len(diff_label_indices) < 1:
                continue

            positive_idx = same_label_indices[np.argmax(
                distance_matrix[anchor_idx, same_label_indices].detach().cpu().numpy()
            )]
            same_label_indices = same_label_indices[same_label_indices != anchor_idx]
            if len(same_label_indices) > 0:
                positive_idx = same_label_indices[np.argmax(
                    distance_matrix[anchor_idx, same_label_indices].detach().cpu().numpy()
                )]
            else:
                continue

            negative_candidates = distance_matrix[anchor_idx, diff_label_indices]
            mask = negative_candidates < (distance_matrix[anchor_idx, positive_idx] + self.margin)
            hard_negatives = diff_label_indices[mask.detach().cpu().numpy()]

            if len(hard_negatives) > 0:
                negative_idx = hard_negatives[np.argmin(
                    negative_candidates[mask].detach().cpu().numpy()
                )]
            else:
                negative_idx = diff_label_indices[np.argmin(
                    negative_candidates.detach().cpu().numpy()
                )]

            anchors.append(embeddings[anchor_idx])
            positives.append(embeddings[positive_idx])
            negatives.append(embeddings[negative_idx])

        if not anchors:
            return None, None, None

        return (
            torch.stack(anchors),
            torch.stack(positives),
            torch.stack(negatives),
        )


class VoiceprintSiameseModel:
    def __init__(self, input_dim: int = 200, embedding_dim: int = 128,
                 margin: float = 0.5, device: Optional[str] = None):
        self.input_dim = input_dim
        self.embedding_dim = embedding_dim
        self.margin = margin

        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = torch.device(device)

        self.model = SiameseEmbeddingNet(
            input_dim=input_dim,
            embedding_dim=embedding_dim
        ).to(self.device)

        self.triplet_loss = TripletLoss(margin=margin, distance_metric='cosine')
        self.triplet_miner = OnlineTripletMining(margin=margin, distance_metric='cosine')

    def get_embedding(self, feature_vector: np.ndarray) -> np.ndarray:
        self.model.eval()
        feature_tensor = torch.tensor(feature_vector, dtype=torch.float32).to(self.device)
        embedding = self.model.get_embedding(feature_tensor)
        return embedding.cpu().numpy()

    def compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        embed1 = self.get_embedding(feat1)
        embed2 = self.get_embedding(feat2)

        norm1 = np.linalg.norm(embed1) + 1e-10
        norm2 = np.linalg.norm(embed2) + 1e-10
        similarity = float(np.dot(embed1 / norm1, embed2 / norm2))

        return similarity

    def verify(self, input_feat: np.ndarray, stored_feats: list,
               threshold: float = 0.7) -> Tuple[bool, float]:
        if not stored_feats:
            return False, 0.0

        max_similarity = 0.0
        for stored_feat in stored_feats:
            similarity = self.compute_similarity(input_feat, np.array(stored_feat))
            if similarity > max_similarity:
                max_similarity = similarity

        return max_similarity >= threshold, max_similarity

    def save(self, path: str):
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'input_dim': self.input_dim,
            'embedding_dim': self.embedding_dim,
            'margin': self.margin,
        }, path)

    def load(self, path: str, map_location: Optional[str] = None):
        if map_location is None:
            map_location = self.device

        checkpoint = torch.load(path, map_location=map_location)
        self.input_dim = checkpoint.get('input_dim', self.input_dim)
        self.embedding_dim = checkpoint.get('embedding_dim', self.embedding_dim)
        self.margin = checkpoint.get('margin', self.margin)

        self.model = SiameseEmbeddingNet(
            input_dim=self.input_dim,
            embedding_dim=self.embedding_dim
        ).to(self.device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.model.eval()

        return self


import numpy as np
