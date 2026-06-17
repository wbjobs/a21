# Models directory

This directory stores trained Siamese network models and normalizer files.

## File Structure

- `voiceprint_siamese.pt` - Trained Siamese network model (PyTorch format)
- `normalizer.pkl` - Pickled AdaptiveNormalizer instance

## Training the Model

Run the training script from the backend directory:

```bash
python scripts/train_siamese.py --epochs 100 --output models/voiceprint_siamese.pt
```

Or use the API endpoint (admin only):

```
POST /api/voice/model/train?n_epochs=100
```

## Model Architecture

- Input: 200-dimensional MFCC feature vector
- Embedding: 128-dimensional L2-normalized vector
- Layers: 512 -> 384 -> 256 -> 128 with BatchNorm and Dropout
- Loss: Triplet loss with margin 0.5
- Distance: Cosine similarity

## Hot Reload

The ModelManager automatically detects file changes and reloads the model
every 5 seconds. You can also trigger a manual reload via API:

```
POST /api/voice/model/reload
```