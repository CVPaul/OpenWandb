#!/usr/bin/env python3
"""
OpenWandb Demo — 多模型超参搜索: 非线性函数回归
================================================

本脚本演示如何使用 wandb SDK 进行完整的 ML 实验追踪，包括:
  ✓ wandb.init()     — 初始化实验 (project, config, tags, notes, group, job_type)
  ✓ wandb.config     — 记录超参数 (lr, hidden_sizes, activation, batch_size, ...)
  ✓ wandb.log()      — 记录训练指标 (loss, mae, r2, learning_rate)
  ✓ 命名空间分组       — train/* 和 val/* 指标自动分组
  ✓ wandb.summary    — 记录最终/最佳指标
  ✓ wandb.Table      — 记录预测结果对比表 (y_true vs y_pred)
  ✓ wandb.Artifact   — 保存模型权重为 JSON artifact
  ✓ 多 Run 对比       — 不同模型架构 + 超参数的横向对比
  ✓ Tags & Notes     — 用于筛选和记录实验上下文
  ✓ Group            — 将相关 run 归组，便于批量对比

场景: 合成非线性回归 y = sin(x1)*cos(x2) + 0.5*x3^2 + ε
模型: 纯 NumPy 实现的多层感知机 (MLP)，无需 PyTorch/TensorFlow

用法:
    python openwandb-demo.py

环境变量:
    WANDB_BASE_URL  — OpenWandb 服务地址 (默认 http://localhost:8080)
    WANDB_API_KEY   — API 密钥 (默认 local0000...)

生成方式: openwandb demo
"""

import math
import os
import sys
import time

import numpy as np

# ═══════════════════════════════════════════════════════════════
# 配置区 — 可自由修改
# ═══════════════════════════════════════════════════════════════

SERVER_URL = os.environ.get("WANDB_BASE_URL", "{server_url}")
API_KEY = os.environ.get("WANDB_API_KEY", "{api_key}")
PROJECT = "{project}"
NUM_RUNS = {num_runs}
EPOCHS = {epochs}

# 数据集参数
N_TRAIN = 2000
N_VAL = 500
N_FEATURES = 5
NOISE_STD = 0.1


# ═══════════════════════════════════════════════════════════════
# 1. 合成数据生成
# ═══════════════════════════════════════════════════════════════

def generate_dataset(n_samples, n_features=5, noise_std=0.1, seed=42):
    """生成非线性回归数据集

    y = sin(x1) * cos(x2) + 0.5 * x3^2 + 0.3 * x4 - 0.2 * x5 + ε

    特征设计:
    - x1, x2: 非线性交互项 (sin * cos)
    - x3: 二次项
    - x4, x5: 线性项
    - ε: 高斯噪声
    """
    rng = np.random.RandomState(seed)
    X = rng.randn(n_samples, n_features) * 2  # 均值0, 标准差2

    y = (np.sin(X[:, 0]) * np.cos(X[:, 1])
         + 0.5 * X[:, 2] ** 2
         + 0.3 * X[:, 3]
         - 0.2 * X[:, 4]
         + rng.randn(n_samples) * noise_std)

    return X, y


def normalize(X_train, X_val):
    """Z-score 标准化"""
    mu = X_train.mean(axis=0)
    sigma = X_train.std(axis=0) + 1e-8
    return (X_train - mu) / sigma, (X_val - mu) / sigma, mu, sigma


# ═══════════════════════════════════════════════════════════════
# 2. 纯 NumPy MLP 实现
# ═══════════════════════════════════════════════════════════════

class NumpyMLP:
    """多层感知机 (纯 NumPy, 支持任意深度)

    特性:
    - He 权重初始化
    - ReLU / Tanh / LeakyReLU 激活函数
    - Mini-batch SGD + 可选 L2 正则化
    - Cosine Annealing 学习率调度
    """

    def __init__(self, layer_sizes, activation="relu", seed=42):
        """
        Args:
            layer_sizes: [input_dim, hidden1, hidden2, ..., output_dim]
            activation: "relu", "tanh", or "leaky_relu"
            seed: 随机种子
        """
        self.layer_sizes = layer_sizes
        self.activation_name = activation
        self.rng = np.random.RandomState(seed)
        self.n_layers = len(layer_sizes) - 1

        # He 初始化权重
        self.weights = []
        self.biases = []
        for i in range(self.n_layers):
            fan_in = layer_sizes[i]
            fan_out = layer_sizes[i + 1]
            scale = np.sqrt(2.0 / fan_in)
            W = self.rng.randn(fan_in, fan_out) * scale
            b = np.zeros(fan_out)
            self.weights.append(W)
            self.biases.append(b)

        # 缓存前向传播中间结果 (反向传播用)
        self._cache = {}

    def _activate(self, z):
        if self.activation_name == "relu":
            return np.maximum(0, z)
        elif self.activation_name == "tanh":
            return np.tanh(z)
        elif self.activation_name == "leaky_relu":
            return np.where(z > 0, z, 0.01 * z)
        raise ValueError(f"Unknown activation: {self.activation_name}")

    def _activate_grad(self, z):
        if self.activation_name == "relu":
            return (z > 0).astype(np.float64)
        elif self.activation_name == "tanh":
            t = np.tanh(z)
            return 1 - t ** 2
        elif self.activation_name == "leaky_relu":
            return np.where(z > 0, 1.0, 0.01)
        raise ValueError(f"Unknown activation: {self.activation_name}")

    def forward(self, X):
        """前向传播"""
        self._cache["a0"] = X
        a = X
        for i in range(self.n_layers):
            z = a @ self.weights[i] + self.biases[i]
            self._cache[f"z{i + 1}"] = z
            if i < self.n_layers - 1:  # 隐藏层用激活
                a = self._activate(z)
            else:  # 输出层线性
                a = z
            self._cache[f"a{i + 1}"] = a
        return a.ravel()

    def backward(self, y_true):
        """反向传播 (MSE loss)"""
        m = len(y_true)
        y_pred = self._cache[f"a{self.n_layers}"].ravel()

        # 输出层梯度: dL/da = 2/m * (y_pred - y_true)
        delta = (2.0 / m) * (y_pred - y_true).reshape(-1, 1)

        self._grads_w = [None] * self.n_layers
        self._grads_b = [None] * self.n_layers

        for i in range(self.n_layers - 1, -1, -1):
            a_prev = self._cache[f"a{i}"]
            self._grads_w[i] = a_prev.T @ delta
            self._grads_b[i] = delta.sum(axis=0)

            if i > 0:
                delta = delta @ self.weights[i].T
                z = self._cache[f"z{i}"]
                delta = delta * self._activate_grad(z)

    def update(self, lr, weight_decay=0.0):
        """SGD 参数更新 + L2 正则化"""
        for i in range(self.n_layers):
            self.weights[i] -= lr * (self._grads_w[i] + weight_decay * self.weights[i])
            self.biases[i] -= lr * self._grads_b[i]

    def predict(self, X):
        return self.forward(X)

    def count_params(self):
        total = 0
        for i in range(self.n_layers):
            total += self.weights[i].size + self.biases[i].size
        return total


# ═══════════════════════════════════════════════════════════════
# 3. 评估指标
# ═══════════════════════════════════════════════════════════════

def mse_loss(y_true, y_pred):
    return np.mean((y_true - y_pred) ** 2)


def mae_metric(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))


def r2_score(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    return 1.0 - ss_res / (ss_tot + 1e-8)


# ═══════════════════════════════════════════════════════════════
# 4. 学习率调度器
# ═══════════════════════════════════════════════════════════════

def cosine_annealing_lr(base_lr, epoch, total_epochs, min_lr=1e-6):
    """Cosine Annealing 学习率衰减"""
    return min_lr + 0.5 * (base_lr - min_lr) * (1 + math.cos(math.pi * epoch / total_epochs))


# ═══════════════════════════════════════════════════════════════
# 5. 训练函数 — wandb 完整集成
# ═══════════════════════════════════════════════════════════════

def train_model(config, project_name, group_name, run_index, total_runs):
    """训练单个模型，完整展示 wandb SDK 功能"""
    import wandb

    name = config["name"]
    print(f"\n[Run {run_index}/{total_runs}] {name} "
          f"(hidden={config['hidden_sizes']}, lr={config['lr']})")
    print("-" * 60)

    # ── wandb.init: 初始化实验 ──
    run = wandb.init(
        project=project_name,
        name=name,
        config=config,
        tags=config["tags"],
        notes=config["notes"],
        group=group_name,
        job_type="train",
    )

    # ── 数据准备 ──
    X_train, y_train = generate_dataset(
        N_TRAIN, N_FEATURES, NOISE_STD, seed=config["seed"]
    )
    X_val, y_val = generate_dataset(
        N_VAL, N_FEATURES, NOISE_STD, seed=config["seed"] + 1000
    )
    X_train, X_val, _, _ = normalize(X_train, X_val)

    # ── 构建模型 ──
    layer_sizes = [N_FEATURES] + config["hidden_sizes"] + [1]
    model = NumpyMLP(
        layer_sizes=layer_sizes,
        activation=config["activation"],
        seed=config["seed"],
    )

    total_params = model.count_params()
    wandb.config.update({"total_params": total_params}, allow_val_change=True)

    # ── 训练循环 ──
    epochs = config["epochs"]
    batch_size = config["batch_size"]
    base_lr = config["lr"]
    weight_decay = config["weight_decay"]
    n_batches = max(1, len(X_train) // batch_size)

    best_val_loss = float("inf")
    best_epoch = 0
    global_step = 0
    t0 = time.time()

    for epoch in range(1, epochs + 1):
        # Cosine annealing LR
        current_lr = cosine_annealing_lr(base_lr, epoch - 1, epochs)

        # Shuffle 训练数据
        perm = np.random.permutation(len(X_train))
        X_shuffled = X_train[perm]
        y_shuffled = y_train[perm]

        epoch_train_loss = 0.0
        for batch_idx in range(n_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(X_train))
            X_batch = X_shuffled[start:end]
            y_batch = y_shuffled[start:end]

            # Forward + Backward + Update
            y_pred = model.forward(X_batch)
            loss = mse_loss(y_batch, y_pred)
            model.backward(y_batch)
            model.update(current_lr, weight_decay)

            epoch_train_loss += loss

            # ── wandb.log: per-batch 指标 ──
            global_step += 1
            wandb.log({
                "train/batch_loss": loss,
                "global_step": global_step,
            })

        epoch_train_loss /= n_batches

        # ── 验证 ──
        y_val_pred = model.predict(X_val)
        val_loss = mse_loss(y_val, y_val_pred)
        val_mae = mae_metric(y_val, y_val_pred)
        val_r2 = r2_score(y_val, y_val_pred)

        # ── wandb.log: per-epoch 指标 (命名空间分组) ──
        wandb.log({
            "epoch": epoch,
            "train/epoch_loss": epoch_train_loss,
            "val/epoch_loss": val_loss,
            "val/mae": val_mae,
            "val/r2_score": val_r2,
            "learning_rate": current_lr,
        })

        # 记录最佳模型
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch

        # 每 10 个 epoch 或最后一个 epoch 打印
        if epoch % 10 == 0 or epoch == epochs:
            print(f"  Epoch {epoch:3d}/{epochs}  "
                  f"train_loss={epoch_train_loss:.4f}  "
                  f"val_loss={val_loss:.4f}  "
                  f"val_r2={val_r2:.3f}  "
                  f"lr={current_lr:.6f}")

    training_time = time.time() - t0

    # ── wandb.summary: 最终/最佳指标 ──
    wandb.summary["best_val_loss"] = best_val_loss
    wandb.summary["best_epoch"] = best_epoch
    wandb.summary["total_params"] = total_params
    wandb.summary["training_time_sec"] = round(training_time, 2)
    wandb.summary["final_train_loss"] = epoch_train_loss
    wandb.summary["final_val_loss"] = val_loss
    wandb.summary["final_val_mae"] = val_mae
    wandb.summary["final_val_r2"] = val_r2

    print(f"  ✓ best_val_loss={best_val_loss:.4f} @ epoch {best_epoch}  "
          f"({training_time:.1f}s, {total_params} params)")

    # ── wandb.Table: 记录预测样本对比表 ──
    try:
        n_samples = min(50, len(X_val))
        table = wandb.Table(columns=["sample_id", "y_true", "y_pred", "abs_error"])
        for i in range(n_samples):
            err = abs(y_val[i] - y_val_pred[i])
            table.add_data(i, round(float(y_val[i]), 4),
                           round(float(y_val_pred[i]), 4), round(float(err), 4))
        wandb.log({"predictions": table})
        print(f"  ✓ Logged prediction table ({n_samples} samples)")
    except Exception as e:
        print(f"  ⚠ Table logging skipped: {e}")

    # ── wandb.Artifact: 保存模型权重 ──
    model_path = None
    try:
        import json as _json
        import tempfile
        model_data = {
            "layer_sizes": layer_sizes,
            "activation": config["activation"],
            "weights": [w.tolist() for w in model.weights],
            "biases": [b.tolist() for b in model.biases],
            "best_val_loss": best_val_loss,
            "best_epoch": best_epoch,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix=f"model-{name}-",
            delete=False, dir="."
        ) as f:
            _json.dump(model_data, f, indent=2)
            model_path = f.name

        artifact = wandb.Artifact(
            name=f"model-{name}",
            type="model",
            description=f"Trained {name} MLP weights (val_loss={best_val_loss:.4f})",
            metadata={
                "architecture": str(layer_sizes),
                "activation": config["activation"],
                "total_params": total_params,
                "best_val_loss": best_val_loss,
            }
        )
        artifact.add_file(model_path)
        run.log_artifact(artifact)
        print(f"  ✓ Logged artifact: model-{name}")
    except Exception as e:
        print(f"  ⚠ Artifact logging skipped: {e}")
    finally:
        if model_path:
            try:
                os.remove(model_path)
            except OSError:
                pass

    # ── wandb.finish: 正确收尾 ──
    wandb.finish()


# ═══════════════════════════════════════════════════════════════
# 6. Run 配置 — 超参搜索矩阵
# ═══════════════════════════════════════════════════════════════

def get_run_configs(num_runs, epochs):
    """生成超参搜索配置矩阵"""
    all_configs = [
        {
            "name": "small-fast",
            "hidden_sizes": [32],
            "lr": 0.01,
            "batch_size": 64,
            "activation": "relu",
            "weight_decay": 1e-4,
            "seed": 42,
            "tags": ["demo", "regression", "small", "fast-lr"],
            "notes": "小模型 + 高学习率: 快速收敛, 可能欠拟合。单隐藏层 32 units, "
                     "适合低复杂度任务。",
        },
        {
            "name": "medium-balanced",
            "hidden_sizes": [64, 32],
            "lr": 0.005,
            "batch_size": 32,
            "activation": "relu",
            "weight_decay": 5e-5,
            "seed": 123,
            "tags": ["demo", "regression", "medium", "balanced"],
            "notes": "中等模型 + 适中学习率: 平衡收敛速度和泛化能力。"
                     "两隐藏层 [64, 32], 通常是非线性回归的较优选择。",
        },
        {
            "name": "large-deep",
            "hidden_sizes": [128, 64, 32],
            "lr": 0.001,
            "batch_size": 16,
            "activation": "leaky_relu",
            "weight_decay": 1e-4,
            "seed": 7,
            "tags": ["demo", "regression", "large", "deep"],
            "notes": "大模型 + 低学习率 + LeakyReLU: 更强表达能力, 收敛较慢。"
                     "三隐藏层 [128, 64, 32], 使用 LeakyReLU 缓解 dying ReLU。",
        },
        {
            "name": "tanh-medium",
            "hidden_sizes": [64, 64],
            "lr": 0.003,
            "batch_size": 32,
            "activation": "tanh",
            "weight_decay": 1e-4,
            "seed": 99,
            "tags": ["demo", "regression", "medium", "tanh"],
            "notes": "Tanh 激活 + 双层等宽网络: 对比 ReLU 在非线性回归中的表现。"
                     "Tanh 输出有界 [-1,1], 可能在此类任务中有优势。",
        },
        {
            "name": "wide-shallow",
            "hidden_sizes": [256],
            "lr": 0.008,
            "batch_size": 64,
            "activation": "relu",
            "weight_decay": 2e-4,
            "seed": 55,
            "tags": ["demo", "regression", "wide", "shallow"],
            "notes": "宽浅模型: 单隐藏层 256 units。对比深窄 vs 宽浅网络的效果差异。"
                     "更多参数集中在单层, 强 L2 正则防止过拟合。",
        },
    ]

    configs = all_configs[:num_runs]
    for cfg in configs:
        cfg["epochs"] = epochs

    return configs


# ═══════════════════════════════════════════════════════════════
# 7. 主函数
# ═══════════════════════════════════════════════════════════════

def main():
    # 设置环境变量
    os.environ.setdefault("WANDB_BASE_URL", SERVER_URL)
    os.environ.setdefault("WANDB_API_KEY", API_KEY)

    # 检查 wandb SDK
    try:
        import wandb
    except ImportError:
        print("ERROR: wandb SDK not installed. Run: pip install wandb")
        sys.exit(1)

    group_name = f"hyperparam-search-{time.strftime('%Y%m%d-%H%M%S')}"

    print()
    print("=" * 60)
    print("  OpenWandb Demo — Multi-Model Hyperparameter Search")
    print("=" * 60)
    print(f"  Server:     {SERVER_URL}")
    print(f"  Project:    {PROJECT}")
    print(f"  Runs:       {NUM_RUNS}")
    print(f"  Epochs:     {EPOCHS}")
    print(f"  Group:      {group_name}")
    print(f"  Dataset:    {N_TRAIN} train / {N_VAL} val samples")
    print(f"  Task:       Nonlinear regression (synthetic)")
    print("=" * 60)

    configs = get_run_configs(NUM_RUNS, EPOCHS)
    t_start = time.time()

    for idx, cfg in enumerate(configs, 1):
        train_model(cfg, PROJECT, group_name, idx, len(configs))

    total_time = time.time() - t_start

    print()
    print("=" * 60)
    print(f"  ✅ Demo complete! ({total_time:.1f}s total)")
    print()
    print(f"  Open your browser to view results:")
    print(f"    Dashboard:  {SERVER_URL}")
    print(f"    Project:    {SERVER_URL}/projects/default/{PROJECT}")
    print()
    print(f"  What to explore in the UI:")
    print(f"    • Compare val/epoch_loss curves across all runs")
    print(f"    • Check which architecture achieved best val/r2_score")
    print(f"    • Filter runs by tags (small/medium/large)")
    print(f"    • View run config to see hyperparameter differences")
    print(f"    • Open individual runs to inspect per-batch train/batch_loss")
    print()
    print(f"  To re-run or customize:")
    print(f"    python openwandb-demo.py")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
