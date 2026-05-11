#!/usr/bin/env python3
"""
OpenWandb v0.2 — 示例训练脚本
演示如何使用 wandb SDK 连接 OpenWandb Server

使用方法:
    1. 启动 OpenWandb Server:
       python run_server.py

    2. 运行此脚本:
       python example_train.py

    环境变量会自动设置为连接本地服务器。
    你也可以在 Settings 页面创建新的 API Key 来替代默认 Key。
"""
import math
import os
import random
import time

# 自动设置环境变量 (如果未设置)
os.environ.setdefault("WANDB_BASE_URL", "http://localhost:8080")
os.environ.setdefault("WANDB_API_KEY", "local0000000000000000000000000000000000000000")
os.environ.setdefault("WANDB_MODE", "online")

import wandb


def simulate_training():
    """模拟一个典型的深度学习训练过程"""

    # 超参数配置
    config = {
        "learning_rate": random.choice([0.001, 0.01, 0.0001]),
        "batch_size": random.choice([32, 64, 128]),
        "epochs": 50,
        "optimizer": random.choice(["adam", "sgd", "adamw"]),
        "model": random.choice(["resnet18", "resnet50", "vgg16"]),
        "dropout": round(random.uniform(0.1, 0.5), 2),
        "weight_decay": random.choice([1e-4, 1e-5, 5e-4]),
        "dataset": "CIFAR-10",
        "architecture": "CNN",
    }

    # 初始化 wandb run
    run = wandb.init(
        project="demo-training",
        config=config,
        tags=["demo", config["model"], config["optimizer"]],
        notes=f"Demo training with {config['model']} and {config['optimizer']}",
    )

    print(f"\n{'='*60}")
    print(f"  OpenWandb Demo Training")
    print(f"  Run ID: {run.id}")
    print(f"  Model: {config['model']}")
    print(f"  LR: {config['learning_rate']}, BS: {config['batch_size']}")
    print(f"  Optimizer: {config['optimizer']}")
    print(f"{'='*60}\n")

    # 模拟训练
    initial_loss = random.uniform(2.0, 4.0)
    best_accuracy = 0
    total_steps = config["epochs"] * 10

    for epoch in range(config["epochs"]):
        for batch in range(10):
            step = epoch * 10 + batch
            progress = step / total_steps

            # 模拟 loss 下降 (带噪声)
            base_loss = initial_loss * math.exp(-3 * progress)
            noise = random.gauss(0, 0.05 * (1 - progress))
            train_loss = max(0.01, base_loss + noise)

            # 模拟 accuracy 上升
            base_accuracy = 1 - math.exp(-4 * progress)
            accuracy = min(0.99, base_accuracy + random.gauss(0, 0.02))
            accuracy = max(0, accuracy)

            # 验证指标
            val_loss = train_loss * random.uniform(1.05, 1.3)
            val_accuracy = accuracy * random.uniform(0.9, 1.0)

            # 记录指标
            wandb.log({
                "train/loss": train_loss,
                "train/accuracy": accuracy,
                "val/loss": val_loss,
                "val/accuracy": val_accuracy,
                "learning_rate": config["learning_rate"] * (1 - 0.5 * progress),
                "epoch": epoch,
            }, step=step)

            best_accuracy = max(best_accuracy, val_accuracy)
            time.sleep(0.05)

        print(f"  Epoch {epoch+1:3d}/{config['epochs']}  |  "
              f"loss: {train_loss:.4f}  |  acc: {accuracy:.4f}  |  "
              f"val_loss: {val_loss:.4f}  |  val_acc: {val_accuracy:.4f}")

    # 记录最终 summary
    wandb.summary["best_accuracy"] = best_accuracy
    wandb.summary["final_loss"] = train_loss
    wandb.summary["total_epochs"] = config["epochs"]

    print(f"\n{'='*60}")
    print(f"  Training complete!")
    print(f"  Best accuracy: {best_accuracy:.4f}")
    print(f"  Final loss: {train_loss:.4f}")
    print(f"  View at: {os.environ.get('WANDB_BASE_URL', 'http://localhost:8080')}")
    print(f"{'='*60}\n")

    wandb.finish()


if __name__ == "__main__":
    simulate_training()
