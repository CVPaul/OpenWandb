#!/usr/bin/env python3
"""
OpenWandb — Example Training Script
Demonstrates how to use the wandb SDK with an OpenWandb server.

Usage:
    1. Start the OpenWandb server:
       python run_server.py

    2. Run this script:
       python example_train.py

    Environment variables are auto-set to connect to the local server.
    You can also create a new API Key in the Settings page to replace the default.
"""
import math
import os
import random
import time

# Auto-set environment variables (if not already set)
os.environ.setdefault("WANDB_BASE_URL", "http://localhost:8080")
os.environ.setdefault("WANDB_API_KEY", "local0000000000000000000000000000000000000000")
os.environ.setdefault("WANDB_MODE", "online")

import wandb


def simulate_training():
    """Simulate a typical deep learning training process."""

    # Hyperparameter configuration
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

    # Initialize wandb run
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

    # Simulate training
    initial_loss = random.uniform(2.0, 4.0)
    best_accuracy = 0
    total_steps = config["epochs"] * 10

    for epoch in range(config["epochs"]):
        for batch in range(10):
            step = epoch * 10 + batch
            progress = step / total_steps

            # Simulate loss decreasing (with noise)
            base_loss = initial_loss * math.exp(-3 * progress)
            noise = random.gauss(0, 0.05 * (1 - progress))
            train_loss = max(0.01, base_loss + noise)

            # Simulate accuracy increasing
            base_accuracy = 1 - math.exp(-4 * progress)
            accuracy = min(0.99, base_accuracy + random.gauss(0, 0.02))
            accuracy = max(0, accuracy)

            # Validation metrics
            val_loss = train_loss * random.uniform(1.05, 1.3)
            val_accuracy = accuracy * random.uniform(0.9, 1.0)

            # Log metrics
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

    # Log final summary
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
