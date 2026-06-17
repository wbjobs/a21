import numpy as np
from typing import Tuple, Optional
from scipy.spatial.distance import cdist


class DynamicTimeWarping:
    def __init__(self, window_size: Optional[int] = None, distance_metric: str = 'cosine'):
        self.window_size = window_size
        self.distance_metric = distance_metric

    def compute_distance_matrix(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        if len(x.shape) == 1:
            x = x.reshape(-1, 1)
        if len(y.shape) == 1:
            y = y.reshape(-1, 1)

        return cdist(x, y, metric=self.distance_metric)

    def align(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float, np.ndarray]:
        n, m = len(x), len(y)
        dist_matrix = self.compute_distance_matrix(x, y)

        dtw_matrix = np.full((n + 1, m + 1), np.inf)
        dtw_matrix[0, 0] = 0

        if self.window_size is None:
            for i in range(1, n + 1):
                for j in range(1, m + 1):
                    cost = dist_matrix[i - 1, j - 1]
                    dtw_matrix[i, j] = cost + min(
                        dtw_matrix[i - 1, j],
                        dtw_matrix[i, j - 1],
                        dtw_matrix[i - 1, j - 1]
                    )
        else:
            w = self.window_size
            for i in range(1, n + 1):
                j_start = max(1, i - w)
                j_end = min(m + 1, i + w + 1)
                for j in range(j_start, j_end):
                    cost = dist_matrix[i - 1, j - 1]
                    dtw_matrix[i, j] = cost + min(
                        dtw_matrix[i - 1, j],
                        dtw_matrix[i, j - 1],
                        dtw_matrix[i - 1, j - 1]
                    )

        path_x, path_y = [], []
        i, j = n, m
        while i > 0 or j > 0:
            path_x.append(i - 1)
            path_y.append(j - 1)
            if i == 0:
                j -= 1
            elif j == 0:
                i -= 1
            else:
                min_prev = min(
                    dtw_matrix[i - 1, j],
                    dtw_matrix[i, j - 1],
                    dtw_matrix[i - 1, j - 1]
                )
                if min_prev == dtw_matrix[i - 1, j - 1]:
                    i -= 1
                    j -= 1
                elif min_prev == dtw_matrix[i - 1, j]:
                    i -= 1
                else:
                    j -= 1

        path_x = np.array(path_x[::-1])
        path_y = np.array(path_y[::-1])

        alignment_cost = dtw_matrix[n, m]
        normalized_cost = alignment_cost / (len(path_x) + 1e-10)

        return path_x, path_y, normalized_cost, dtw_matrix[1:, 1:]

    def warp_feature(self, source: np.ndarray, target: np.ndarray) -> np.ndarray:
        if len(source) == 0 or len(target) == 0:
            return source

        path_x, path_y, _, _ = self.align(source, target)

        warped = np.zeros_like(target)
        counts = np.zeros(len(target), dtype=np.int32)

        for px, py in zip(path_x, path_y):
            if py < len(target):
                warped[py] += source[px]
                counts[py] += 1

        mask = counts > 0
        warped[mask] /= counts[mask]

        for i in range(1, len(warped)):
            if counts[i] == 0:
                warped[i] = warped[i - 1]

        return warped


class FeatureAligner:
    def __init__(self, n_mfcc: int = 40, dtw_window: int = 50):
        self.n_mfcc = n_mfcc
        self.dtw = DynamicTimeWarping(window_size=dtw_window, distance_metric='euclidean')

    def extract_feature_sequence(self, y: np.ndarray, sr: int) -> np.ndarray:
        import librosa

        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=self.n_mfcc, hop_length=512)
        delta = librosa.feature.delta(mfcc)
        delta2 = librosa.feature.delta(mfcc, order=2)

        features = np.vstack([mfcc, delta, delta2])
        return features.T

    def align_sequences(self, seq_a: np.ndarray, seq_b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n_features = seq_a.shape[1]
        aligned_a = np.zeros((len(seq_b), n_features))

        for dim in range(n_features):
            dim_a = seq_a[:, dim]
            dim_b = seq_b[:, dim]
            warped = self.dtw.warp_feature(dim_a, dim_b)
            aligned_a[:, dim] = warped

        return aligned_a, seq_b

    def compute_alignment_similarity(self, seq_a: np.ndarray, seq_b: np.ndarray) -> float:
        aligned_a, seq_b_aligned = self.align_sequences(seq_a, seq_b)

        similarity = 0.0
        n_features = seq_a.shape[1]
        for dim in range(n_features):
            dim_a = aligned_a[:, dim]
            dim_b = seq_b_aligned[:, dim]

            norm_a = np.linalg.norm(dim_a) + 1e-10
            norm_b = np.linalg.norm(dim_b) + 1e-10
            dim_sim = np.dot(dim_a / norm_a, dim_b / norm_b)
            similarity += dim_sim

        return similarity / n_features

    def get_aligned_feature_vector(self, seq_a: np.ndarray, seq_b: np.ndarray) -> np.ndarray:
        aligned_a, _ = self.align_sequences(seq_a, seq_b)

        features = np.concatenate([
            np.mean(aligned_a, axis=0),
            np.std(aligned_a, axis=0),
        ])

        return features
