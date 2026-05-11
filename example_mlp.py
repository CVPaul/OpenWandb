#!/usr/bin/env python3
"""
OpenWandb — 真实 MLP 训练示例 (MNIST 手写数字识别)

这是一个完整的、可直接运行的深度学习训练脚本，使用 PyTorch 构建一个
多层感知机 (MLP) 来识别 MNIST 手写数字，并通过 wandb 记录全部训练过程。

非常适合没有接触过 wandb 的新手:
  - 展示 wandb.init / wandb.log / wandb.finish 三步核心用法
  - 展示如何记录超参数、训练指标、验证指标、学习率等
  - 展示如何用 wandb.summary 保存最终结果
  - 多次运行并修改超参数，即可在 Web UI 中对比不同实验

前置条件:
    pip install torch torchvision wandb

使用方法:
    # 1. 启动 OpenWandb 服务器 (另一个终端)
    python run_server.py

    # 2. 运行训练
    python example_mlp.py

    # 3. 打开浏览器查看结果
    #    http://localhost:8080

    # 4. (可选) 修改超参数再跑一次, 然后在 Web UI 中对比两次实验
    python example_mlp.py --lr 0.01 --hidden 128 --epochs 10
"""
import argparse
import os
import time

# ─── 自动连接本地 OpenWandb 服务器 ───
os.environ.setdefault("WANDB_BASE_URL", "http://localhost:8080")
os.environ.setdefault("WANDB_API_KEY", "local0000000000000000000000000000000000000000")
os.environ.setdefault("WANDB_MODE", "online")

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

import wandb


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 定义模型: 一个简单的 MLP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MLP(nn.Module):
    """
    三层全连接网络 (Multi-Layer Perceptron)
    输入 28×28 灰度图像 → 展平为 784 维 → 两个隐藏层 → 10 类输出
    """

    def __init__(self, hidden_size: int = 256, dropout: float = 0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),                        # 28×28 → 784
            nn.Linear(784, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, 10),          # 10 个数字类别
        )

    def forward(self, x):
        return self.net(x)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 训练一个 epoch
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def train_one_epoch(model, loader, criterion, optimizer, device, epoch, global_step):
    """训练一个 epoch, 每个 batch 都向 wandb 记录 loss"""
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for batch_idx, (images, labels) in enumerate(loader):
        images, labels = images.to(device), labels.to(device)

        # 前向传播
        outputs = model(images)
        loss = criterion(outputs, labels)

        # 反向传播
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # 统计
        running_loss += loss.item() * images.size(0)
        _, predicted = outputs.max(1)
        total += labels.size(0)
        correct += predicted.eq(labels).sum().item()

        # ✨ 核心: 每个 batch 用 wandb.log 记录训练指标
        wandb.log({
            "train/batch_loss": loss.item(),
            "train/learning_rate": optimizer.param_groups[0]["lr"],
            "epoch": epoch,
        }, step=global_step)

        global_step += 1

    epoch_loss = running_loss / total
    epoch_acc = correct / total
    return epoch_loss, epoch_acc, global_step


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@torch.no_grad()
def evaluate(model, loader, criterion, device):
    """在验证集上评估模型"""
    model.eval()
    running_loss = 0.0
    correct = 0
    total = 0

    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        outputs = model(images)
        loss = criterion(outputs, labels)

        running_loss += loss.item() * images.size(0)
        _, predicted = outputs.max(1)
        total += labels.size(0)
        correct += predicted.eq(labels).sum().item()

    return running_loss / total, correct / total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 主训练流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    # ── 命令行参数 (也是超参数, 方便修改后对比) ──
    parser = argparse.ArgumentParser(description="MLP MNIST Training with OpenWandb")
    parser.add_argument("--epochs",     type=int,   default=5,     help="训练轮数 (默认 5)")
    parser.add_argument("--batch-size", type=int,   default=64,    help="批大小 (默认 64)")
    parser.add_argument("--lr",         type=float, default=0.001, help="学习率 (默认 0.001)")
    parser.add_argument("--hidden",     type=int,   default=256,   help="隐藏层大小 (默认 256)")
    parser.add_argument("--dropout",    type=float, default=0.2,   help="Dropout 比例 (默认 0.2)")
    parser.add_argument("--optimizer",  type=str,   default="adam", choices=["adam", "sgd", "adamw"],
                        help="优化器 (默认 adam)")
    parser.add_argument("--seed",       type=int,   default=42,    help="随机种子")
    args = parser.parse_args()

    # 设置随机种子 (可复现)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ✨ wandb 第 1 步: 初始化实验
    #
    #   - project: 项目名 (Web UI 里的分组)
    #   - config:  超参数 (自动记录, 便于对比)
    #   - tags:    标签 (方便筛选)
    #   - notes:   备注
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    run = wandb.init(
        project="mnist-mlp",
        config={
            "epochs":       args.epochs,
            "batch_size":   args.batch_size,
            "learning_rate": args.lr,
            "hidden_size":  args.hidden,
            "dropout":      args.dropout,
            "optimizer":    args.optimizer,
            "model":        "MLP",
            "dataset":      "MNIST",
            "device":       str(device),
            "seed":         args.seed,
        },
        tags=["mlp", "mnist", args.optimizer],
        notes=f"MLP hidden={args.hidden}, lr={args.lr}, opt={args.optimizer}",
    )

    # 从 wandb.config 读取超参数 (推荐做法, 方便 sweep)
    config = wandb.config

    print(f"\n{'='*60}")
    print(f"  🧠 MNIST MLP Training")
    print(f"  Run ID:     {run.id}")
    print(f"  Device:     {device}")
    print(f"  Hidden:     {config.hidden_size}")
    print(f"  LR:         {config.learning_rate}")
    print(f"  Optimizer:  {config.optimizer}")
    print(f"  Batch Size: {config.batch_size}")
    print(f"  Epochs:     {config.epochs}")
    print(f"{'='*60}\n")

    # ── 数据准备 ──
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)),  # MNIST 均值/标准差
    ])

    print("  Downloading MNIST dataset (first time only)...")
    train_dataset = datasets.MNIST("./data_mnist", train=True,  download=True, transform=transform)
    test_dataset  = datasets.MNIST("./data_mnist", train=False, download=True, transform=transform)

    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True,  num_workers=0)
    test_loader  = DataLoader(test_dataset,  batch_size=config.batch_size, shuffle=False, num_workers=0)

    print(f"  Train samples: {len(train_dataset)}")
    print(f"  Test samples:  {len(test_dataset)}")
    print(f"  Batches/epoch: {len(train_loader)}\n")

    # ── 模型 / 损失 / 优化器 ──
    model = MLP(hidden_size=config.hidden_size, dropout=config.dropout).to(device)
    criterion = nn.CrossEntropyLoss()

    if config.optimizer == "adam":
        optimizer = optim.Adam(model.parameters(), lr=config.learning_rate)
    elif config.optimizer == "adamw":
        optimizer = optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    else:
        optimizer = optim.SGD(model.parameters(), lr=config.learning_rate, momentum=0.9)

    # 学习率调度器: 每个 epoch 衰减
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=max(1, config.epochs // 3), gamma=0.5)

    # 记录模型参数量
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Model params:     {total_params:,}")
    print(f"  Trainable params: {trainable_params:,}\n")
    wandb.config.update({"total_params": total_params, "trainable_params": trainable_params})

    # ── 训练循环 ──
    best_val_acc = 0.0
    global_step = 0
    start_time = time.time()

    for epoch in range(1, config.epochs + 1):
        epoch_start = time.time()

        # 训练
        train_loss, train_acc, global_step = train_one_epoch(
            model, train_loader, criterion, optimizer, device, epoch, global_step
        )

        # 验证
        val_loss, val_acc = evaluate(model, test_loader, criterion, device)

        # 学习率调度
        scheduler.step()
        current_lr = optimizer.param_groups[0]["lr"]

        epoch_time = time.time() - epoch_start

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ✨ wandb 第 2 步: 记录每个 epoch 的指标
        #
        #   wandb.log() 可以记录任意 key-value 对
        #   用 "/" 分隔可以在 UI 中自动分组
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        wandb.log({
            "train/epoch_loss":   train_loss,
            "train/epoch_acc":    train_acc,
            "val/loss":           val_loss,
            "val/accuracy":       val_acc,
            "epoch":              epoch,
            "epoch_time_sec":     epoch_time,
            "learning_rate":      current_lr,
        }, step=global_step)

        best_val_acc = max(best_val_acc, val_acc)

        # 打印进度
        print(f"  Epoch {epoch:3d}/{config.epochs}  |  "
              f"train_loss: {train_loss:.4f}  train_acc: {train_acc:.4f}  |  "
              f"val_loss: {val_loss:.4f}  val_acc: {val_acc:.4f}  |  "
              f"lr: {current_lr:.6f}  |  {epoch_time:.1f}s")

    total_time = time.time() - start_time

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ✨ wandb 补充: 用 summary 保存最终结果
    #
    #   summary 中的值会在项目页的运行列表中显示
    #   方便快速对比不同实验的最终效果
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    wandb.summary["best_val_accuracy"]   = best_val_acc
    wandb.summary["final_train_loss"]    = train_loss
    wandb.summary["final_val_loss"]      = val_loss
    wandb.summary["final_val_accuracy"]  = val_acc
    wandb.summary["total_training_time"] = total_time
    wandb.summary["total_params"]        = total_params

    print(f"\n{'='*60}")
    print(f"  ✅ Training complete!")
    print(f"  Best val accuracy:  {best_val_acc:.4f}")
    print(f"  Final val accuracy: {val_acc:.4f}")
    print(f"  Total time:         {total_time:.1f}s")
    print(f"")
    print(f"  📊 View results at: {os.environ.get('WANDB_BASE_URL')}")
    print(f"{'='*60}\n")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ✨ wandb 第 3 步: 结束实验
    #
    #   finish() 会上传所有剩余数据并标记运行为 "finished"
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    wandb.finish()


if __name__ == "__main__":
    main()
