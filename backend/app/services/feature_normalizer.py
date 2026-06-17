import numpy as np
from typing import Optional, Tuple, List
from dataclasses import dataclass, field


@dataclass
class NormalizationStats:
    mean: np.ndarray
    std: np.ndarray
    min: np.ndarray
    max: np.ndarray
    count: int = 0
    feature_dim: int = 0

    def update(self, feature: np.ndarray):
        if self.count == 0:
            self.feature_dim = len(feature)
            self.mean = feature.copy()
            self.std = np.zeros_like(feature)
            self.min = feature.copy()
            self.max = feature.copy()
        else:
            old_mean = self.mean.copy()
            self.mean = (self.mean * self.count + feature) / (self.count + 1)
            self.std = np.sqrt(
                (self.std ** 2 * self.count +
                 (feature - old_mean) * (feature - self.mean)) / (self.count + 1)
            )
            self.min = np.minimum(self.min, feature)
            self.max = np.maximum(self.max, feature)

        self.count += 1


class CMVNNormalizer:
    def __init__(self, feature_dim: int = 200, update_stats: bool = False):
        self.feature_dim = feature_dim
        self.update_stats = update_stats
        self.global_stats = NormalizationStats(
            mean=np.zeros(feature_dim),
            std=np.ones(feature_dim),
            min=np.zeros(feature_dim),
            max=np.ones(feature_dim),
            count=0,
            feature_dim=feature_dim
        )
        self.user_stats: dict[int, NormalizationStats] = {}

    def fit(self, features: np.ndarray):
        if len(features.shape) == 1:
            features = features.reshape(1, -1)

        self.global_stats.mean = np.mean(features, axis=0)
        self.global_stats.std = np.std(features, axis=0) + 1e-10
        self.global_stats.min = np.min(features, axis=0)
        self.global_stats.max = np.max(features, axis=0)
        self.global_stats.count = len(features)

    def normalize(self, feature: np.ndarray, user_id: Optional[int] = None) -> np.ndarray:
        if self.update_stats:
            self.global_stats.update(feature)
            if user_id is not None:
                if user_id not in self.user_stats:
                    self.user_stats[user_id] = NormalizationStats(
                        mean=np.zeros_like(feature),
                        std=np.ones_like(feature),
                        min=np.zeros_like(feature),
                        max=np.ones_like(feature),
                        count=0,
                        feature_dim=len(feature)
                    )
                self.user_stats[user_id].update(feature)

        stats = self.global_stats
        if user_id is not None and user_id in self.user_stats and self.user_stats[user_id].count > 5:
            stats = self.user_stats[user_id]

        normalized = (feature - stats.mean) / (stats.std + 1e-10)

        range_ = stats.max - stats.min + 1e-10
        min_max_norm = (feature - stats.min) / range_
        min_max_norm = min_max_norm * 2 - 1

        return normalized

    def get_user_stats(self, user_id: int) -> Optional[NormalizationStats]:
        return self.user_stats.get(user_id)


class HistogramWarping:
    def __init__(self, n_bins: int = 100, reference_histogram: Optional[np.ndarray] = None):
        self.n_bins = n_bins
        self.reference_histogram = reference_histogram
        self.reference_quantiles = None

    def fit_reference(self, features: np.ndarray):
        if len(features.shape) == 1:
            features = features.reshape(1, -1)

        flat_features = features.flatten()
        quantiles = np.linspace(0, 1, self.n_bins)
        self.reference_quantiles = np.quantile(flat_features, quantiles)
        return self

    def warp(self, feature: np.ndarray) -> np.ndarray:
        if self.reference_quantiles is None:
            return feature

        flat = feature.flatten()
        ranks = np.argsort(np.argsort(flat)) / (len(flat) - 1)

        warped = np.zeros_like(flat)
        for i, rank in enumerate(ranks):
            bin_idx = min(int(rank * (self.n_bins - 1)), self.n_bins - 1)
            warped[i] = self.reference_quantiles[bin_idx]

        return warped.reshape(feature.shape)


class FeatureWarping:
    def __init__(self, feature_dim: int = 200, warp_factor: float = 0.25):
        self.feature_dim = feature_dim
        self.warp_factor = warp_factor

    def time_warp(self, feature_sequence: np.ndarray, sigma: float = 1.0) -> np.ndarray:
        n_frames = len(feature_sequence)
        if n_frames < 2:
            return feature_sequence

        warp_points = int(n_frames * self.warp_factor)
        if warp_points < 2:
            return feature_sequence

        x = np.linspace(0, n_frames - 1, n_frames)
        x_new = x.copy()

        for _ in range(warp_points // 10):
            center = np.random.randint(0, n_frames)
            width = np.random.randint(max(2, n_frames // 4), n_frames // 2)
            amplitude = np.random.uniform(-width * 0.3, width * 0.3)

            gaussian = amplitude * np.exp(-((x - center) ** 2) / (2 * width ** 2))
            x_new = x + gaussian

        x_new = np.clip(x_new, 0, n_frames - 1)

        warped = np.zeros_like(feature_sequence)
        for dim in range(feature_sequence.shape[1]):
            warped[:, dim] = np.interp(x, x_new, feature_sequence[:, dim])

        return warped

    def frequency_warp(self, feature_sequence: np.ndarray) -> np.ndarray:
        n_dims = feature_sequence.shape[1]
        if n_dims < 2:
            return feature_sequence

        warp_points = max(2, int(n_dims * self.warp_factor))
        dims = np.arange(n_dims)
        new_dims = dims.astype(float)

        for _ in range(warp_points // 5):
            center = np.random.randint(0, n_dims)
            width = np.random.randint(max(2, n_dims // 8), n_dims // 4)
            amplitude = np.random.uniform(-width * 0.2, width * 0.2)

            gaussian = amplitude * np.exp(-((dims - center) ** 2) / (2 * width ** 2))
            new_dims = new_dims + gaussian

        new_dims = np.clip(new_dims, 0, n_dims - 1)

        warped = np.zeros_like(feature_sequence)
        for frame in range(len(feature_sequence)):
            warped[frame, :] = np.interp(dims, new_dims, feature_sequence[frame, :])

        return warped


class AdaptiveNormalizer:
    def __init__(self, feature_dim: int = 200, enable_cmvn: bool = True,
                 enable_histogram: bool = True, enable_warping: bool = False):
        self.feature_dim = feature_dim
        self.cmvn = CMVNNormalizer(feature_dim=feature_dim, update_stats=False)
        self.histogram = HistogramWarping(n_bins=100)
        self.warping = FeatureWarping(feature_dim=feature_dim)
        self.enable_cmvn = enable_cmvn
        self.enable_histogram = enable_histogram
        self.enable_warping = enable_warping

        self._default_stats_init = False

    def _init_default_stats(self):
        if self._default_stats_init:
            return

        mean = np.zeros(self.feature_dim)
        std = np.ones(self.feature_dim)
        min_val = -3 * np.ones(self.feature_dim)
        max_val = 3 * np.ones(self.feature_dim)

        self.cmvn.global_stats = NormalizationStats(
            mean=mean, std=std, min=min_val, max=max_val,
            count=1000, feature_dim=self.feature_dim
        )

        ref_data = np.random.randn(10000, self.feature_dim)
        self.histogram.fit_reference(ref_data)

        self._default_stats_init = True

    def normalize(self, feature: np.ndarray, user_id: Optional[int] = None) -> np.ndarray:
        self._init_default_stats()

        result = feature.copy()

        if self.enable_cmvn:
            result = self.cmvn.normalize(result, user_id=user_id)

        if self.enable_histogram:
            result = self.histogram.warp(result)

        norm = np.linalg.norm(result) + 1e-10
        result = result / norm

        return result

    def normalize_sequence(self, feature_sequence: np.ndarray,
                           user_id: Optional[int] = None) -> np.ndarray:
        self._init_default_stats()

        result = feature_sequence.copy()

        if self.enable_warping:
            result = self.warping.time_warp(result)
            result = self.warping.frequency_warp(result)

        normalized_frames = np.array([
            self.normalize(frame, user_id=user_id)
            for frame in result
        ])

        return normalized_frames
