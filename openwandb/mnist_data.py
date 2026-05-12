"""
OpenWandb — MNIST data loader (bundled in pip package)
"""
import numpy as np
from pathlib import Path


def load_mnist():
    """Load bundled MNIST subset (10K train + 2K test).

    Returns:
        tuple: (train_images, train_labels, test_images, test_labels)
            - train_images: np.ndarray, shape (10000, 28, 28), dtype uint8
            - train_labels: np.ndarray, shape (10000,), dtype uint8
            - test_images:  np.ndarray, shape (2000, 28, 28), dtype uint8
            - test_labels:  np.ndarray, shape (2000,), dtype uint8
    """
    data_path = Path(__file__).parent / "data" / "mnist_demo.npz"
    if not data_path.exists():
        raise FileNotFoundError(
            "MNIST data file not found at %s. "
            "Please reinstall openwandb: pip install --upgrade openwandb" % data_path
        )
    data = np.load(str(data_path))
    return (
        data["train_images"],
        data["train_labels"],
        data["test_images"],
        data["test_labels"],
    )
