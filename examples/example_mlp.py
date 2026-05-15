#!/usr/bin/env python3
"""
OpenWandb — Real MLP Training Example (MNIST Handwritten Digit Recognition)

A complete, runnable deep learning training script that uses PyTorch to build
a Multi-Layer Perceptron (MLP) for MNIST digit recognition, logging the entire
training process with wandb.

Great for newcomers to wandb:
  - Demonstrates wandb.init / wandb.log / wandb.finish core workflow
  - Shows how to log hyperparameters, training metrics, validation metrics, LR
  - Shows how to use wandb.summary for final results
  - Run multiple times with different hyperparameters to compare in the Web UI

Prerequisites:
    pip install torch torchvision wandb

Usage:
    # 1. Start the OpenWandb server (in another terminal)
    python run_server.py

    # 2. Run training
    python example_mlp.py

    # 3. Open browser to view results
    #    http://localhost:8080

    # 4. (Optional) Modify hyperparameters and run again, then compare in Web UI
    python example_mlp.py --lr 0.01 --hidden 128 --epochs 10
"""
import argparse
import os
import time

# --- Auto-connect to local OpenWandb server ---
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
# 1. Model definition: a simple MLP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MLP(nn.Module):
    """
    Three-layer fully connected network (Multi-Layer Perceptron).
    Input: 28x28 grayscale image -> flatten to 784 -> two hidden layers -> 10 class output
    """

    def __init__(self, hidden_size: int = 256, dropout: float = 0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),                        # 28x28 -> 784
            nn.Linear(784, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, 10),          # 10 digit classes
        )

    def forward(self, x):
        return self.net(x)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Train one epoch
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def train_one_epoch(model, loader, criterion, optimizer, device, epoch, global_step):
    """Train one epoch, logging loss to wandb for each batch."""
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for batch_idx, (images, labels) in enumerate(loader):
        images, labels = images.to(device), labels.to(device)

        # Forward pass
        outputs = model(images)
        loss = criterion(outputs, labels)

        # Backward pass
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # Statistics
        running_loss += loss.item() * images.size(0)
        _, predicted = outputs.max(1)
        total += labels.size(0)
        correct += predicted.eq(labels).sum().item()

        # Core: log training metrics per batch with wandb.log
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
# 3. Validation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@torch.no_grad()
def evaluate(model, loader, criterion, device):
    """Evaluate model on the validation set."""
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
# 4. Main training flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    # -- Command-line arguments (also hyperparameters for easy comparison) --
    parser = argparse.ArgumentParser(description="MLP MNIST Training with OpenWandb")
    parser.add_argument("--epochs",     type=int,   default=5,     help="Number of epochs (default: 5)")
    parser.add_argument("--batch-size", type=int,   default=64,    help="Batch size (default: 64)")
    parser.add_argument("--lr",         type=float, default=0.001, help="Learning rate (default: 0.001)")
    parser.add_argument("--hidden",     type=int,   default=256,   help="Hidden layer size (default: 256)")
    parser.add_argument("--dropout",    type=float, default=0.2,   help="Dropout rate (default: 0.2)")
    parser.add_argument("--optimizer",  type=str,   default="adam", choices=["adam", "sgd", "adamw"],
                        help="Optimizer (default: adam)")
    parser.add_argument("--seed",       type=int,   default=42,    help="Random seed")
    args = parser.parse_args()

    # Set random seed (for reproducibility)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 1: Initialize experiment with wandb
    #
    #   - project: project name (grouping in Web UI)
    #   - config:  hyperparameters (auto-logged for comparison)
    #   - tags:    tags (for filtering)
    #   - notes:   description
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

    # Read hyperparameters from wandb.config (recommended for sweeps)
    config = wandb.config

    print(f"\n{'='*60}")
    print(f"  MNIST MLP Training")
    print(f"  Run ID:     {run.id}")
    print(f"  Device:     {device}")
    print(f"  Hidden:     {config.hidden_size}")
    print(f"  LR:         {config.learning_rate}")
    print(f"  Optimizer:  {config.optimizer}")
    print(f"  Batch Size: {config.batch_size}")
    print(f"  Epochs:     {config.epochs}")
    print(f"{'='*60}\n")

    # -- Data preparation --
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)),  # MNIST mean/std
    ])

    print("  Downloading MNIST dataset (first time only)...")
    train_dataset = datasets.MNIST("./data_mnist", train=True,  download=True, transform=transform)
    test_dataset  = datasets.MNIST("./data_mnist", train=False, download=True, transform=transform)

    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True,  num_workers=0)
    test_loader  = DataLoader(test_dataset,  batch_size=config.batch_size, shuffle=False, num_workers=0)

    print(f"  Train samples: {len(train_dataset)}")
    print(f"  Test samples:  {len(test_dataset)}")
    print(f"  Batches/epoch: {len(train_loader)}\n")

    # -- Model / Loss / Optimizer --
    model = MLP(hidden_size=config.hidden_size, dropout=config.dropout).to(device)
    criterion = nn.CrossEntropyLoss()

    if config.optimizer == "adam":
        optimizer = optim.Adam(model.parameters(), lr=config.learning_rate)
    elif config.optimizer == "adamw":
        optimizer = optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=1e-4)
    else:
        optimizer = optim.SGD(model.parameters(), lr=config.learning_rate, momentum=0.9)

    # Learning rate scheduler: decay every N epochs
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=max(1, config.epochs // 3), gamma=0.5)

    # Log model parameter count
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Model params:     {total_params:,}")
    print(f"  Trainable params: {trainable_params:,}\n")
    wandb.config.update({"total_params": total_params, "trainable_params": trainable_params})

    # -- Training loop --
    best_val_acc = 0.0
    global_step = 0
    start_time = time.time()

    for epoch in range(1, config.epochs + 1):
        epoch_start = time.time()

        # Train
        train_loss, train_acc, global_step = train_one_epoch(
            model, train_loader, criterion, optimizer, device, epoch, global_step
        )

        # Validate
        val_loss, val_acc = evaluate(model, test_loader, criterion, device)

        # LR scheduling
        scheduler.step()
        current_lr = optimizer.param_groups[0]["lr"]

        epoch_time = time.time() - epoch_start

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Step 2: Log epoch-level metrics with wandb
        #
        #   wandb.log() can log any key-value pairs.
        #   Use "/" separators for automatic grouping in the UI.
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

        # Print progress
        print(f"  Epoch {epoch:3d}/{config.epochs}  |  "
              f"train_loss: {train_loss:.4f}  train_acc: {train_acc:.4f}  |  "
              f"val_loss: {val_loss:.4f}  val_acc: {val_acc:.4f}  |  "
              f"lr: {current_lr:.6f}  |  {epoch_time:.1f}s")

    total_time = time.time() - start_time

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Bonus: Use summary to save final results
    #
    #   Values in summary appear in the run list on the project page,
    #   making it easy to quickly compare final results across experiments.
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    wandb.summary["best_val_accuracy"]   = best_val_acc
    wandb.summary["final_train_loss"]    = train_loss
    wandb.summary["final_val_loss"]      = val_loss
    wandb.summary["final_val_accuracy"]  = val_acc
    wandb.summary["total_training_time"] = total_time
    wandb.summary["total_params"]        = total_params

    print(f"\n{'='*60}")
    print(f"  Training complete!")
    print(f"  Best val accuracy:  {best_val_acc:.4f}")
    print(f"  Final val accuracy: {val_acc:.4f}")
    print(f"  Total time:         {total_time:.1f}s")
    print(f"")
    print(f"  View results at: {os.environ.get('WANDB_BASE_URL')}")
    print(f"{'='*60}\n")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 3: Finish the experiment
    #
    #   finish() uploads all remaining data and marks the run as "finished"
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    wandb.finish()


if __name__ == "__main__":
    main()
