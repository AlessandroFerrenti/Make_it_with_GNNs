import torch
import torch.nn as nn
import torch.nn.functional as F
import dgl
import dgl.nn as dglnn
from dgl.data import CoraGraphDataset, CiteseerGraphDataset, PubmedGraphDataset
from dgl import AddSelfLoop
import argparse

import wandb
from monitor import Monitor

class GCN(nn.Module):
    def __init__(self, in_size, hid_size, out_size):
        super().__init__()
        self.layers = nn.ModuleList()
        # two-layer GCN
        self.layers.append(dglnn.GraphConv(in_size, hid_size, activation=F.relu))
        self.layers.append(dglnn.GraphConv(hid_size, out_size))
        self.dropout = nn.Dropout(args.dropout)

    def forward(self, g, features):
        h = features
        for i, layer in enumerate(self.layers):
            if i != 0:
                h = self.dropout(h)
            h = layer(g, h)
        return h
    
def evaluate(g, features, labels, mask, model):
    model.eval()
    with torch.no_grad():
        logits = model(g, features)
        logits = logits[mask]
        labels = labels[mask]
        _, indices = torch.max(logits, dim=1)
        correct = torch.sum(indices == labels)
        return correct.item() * 1.0 / len(labels)


def train(g, features, labels, masks, model):
    # define train/val samples, loss function and optimizer
    train_mask = masks[0]
    val_mask = masks[1]
    loss_fcn = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    # training loop
    for epoch in range(args.epochs):
        model.train()
        wandb.log(monitor.get_sys_info())

        logits = model(g, features)
        loss = loss_fcn(logits[train_mask], labels[train_mask])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        acc = evaluate(g, features, labels, val_mask, model)
        print("Epoch {:05d} | Loss {:.4f} | Accuracy {:.4f} "
              . format(epoch, loss.item(), acc))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="cora",
                        help="Dataset name ('cora', 'citeseer', 'pubmed').")
    parser.add_argument("--epochs", type=int, default=200,
                        help="number of training epochs")
    parser.add_argument("--lr", type=float, default=1e-2,
                        help="learning rate")
    parser.add_argument("--n-hidden", type=int, default=16,
                        help="number of hidden gcn units")
    parser.add_argument("--weight-decay", type=float, default=5e-4,
                        help="Weight for L2 loss")
    parser.add_argument("--dropout", type=float, default=.5,
                        help="dropout")
    parser.add_argument("--architecture", type=str, default="GCN",
                        help="GCN")
    args = parser.parse_args()
    print(f'Training with DGL built-in GraphConv module.')
 
    # load and preprocess dataset
    transform = AddSelfLoop()  # by default, it will first remove self-loops to prevent duplication
    if args.dataset == 'cora':
        data = CoraGraphDataset(transform=transform)
    elif args.dataset == 'citeseer':
        data = CiteseerGraphDataset(transform=transform)
    elif args.dataset == 'pubmed':
        data = PubmedGraphDataset(transform=transform)
    else:
        raise ValueError('Unknown dataset: {}'.format(args.dataset))
    g = data[0]
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    g = g.int().to(device)
    features = g.ndata['feat']
    labels = g.ndata['label']
    masks = g.ndata['train_mask'], g.ndata['val_mask'], g.ndata['test_mask']
        
    # normalization
    degs = g.in_degrees().float()
    norm = torch.pow(degs, -0.5).to(device)
    norm[torch.isinf(norm)] = 0
    g.ndata['norm'] = norm.unsqueeze(1)

    # create GCN model    
    in_size = features.shape[1]
    out_size = data.num_classes
    model = GCN(in_size, args.n_hidden, out_size).to(device)

    # model training
    print('Training...')
    monitor = Monitor()
    wandb.init(project = 'GNN-test', entity='kubework', config=args)

    train(g, features, labels, masks, model)
    
    # test the model
    print('Testing...')
    acc = evaluate(g, features, labels, masks[2], model)
    print("Test accuracy {:.4f}".format(acc))
