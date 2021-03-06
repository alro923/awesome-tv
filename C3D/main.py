from utils import *
from model import *
from datasets import *

import wandb
import argparse

ckpt = None
epochs = 400
workers = 8
device = 'cuda' if torch.cuda.is_available() else 'cpu'
ucf_folder = '/data5/datasets/ucf101'
output_folder = './output/'
wandb_id = wandb.util.generate_id()

def train_and_val(model, train_data_loader, valid_data_loader):
    #import pdb;pdb.set_trace()
    loss_fn = nn.CrossEntropyLoss()
    
    if args.optimizer_type == 'SGD':
        optimizer = optim.SGD(model.parameters(), lr = args.learning_rate, momentum = 0.9, weight_decay = 5e-4)
    elif args.optimizer_type == 'Adam':
        optim_configs = [{'params': model.parameters(), 'lr': args.learning_rate}]
        optimizer = optim.Adam(optim_configs, lr=args.learning_rate, weight_decay=5e-4)
    elif args.optimizer_type =='SGD_params':
        train_params = [{'params': get_1x_lr_params(model), 'lr': args.learning_rate},
                {'params': get_10x_lr_params(model), 'lr': args.learning_rate * 10}]
        optimizer = optim.SGD(train_params, lr = args.learning_rate, momentum = 0.9, weight_decay = 5e-4)
    

    if args.scheduler == 'step':
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=args.step_size, gamma=0.1)
    elif args.scheduler == 'reduce':
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.1, verbose=True)
    model = model.to(device)
    wandb.watch(models = model, criterion = loss_fn, log = 'all')
    
    with torch.autograd.set_detect_anomaly(True):
        for epoch in tqdm(range(epochs)):
            model.train()
            train_loss = 0.0
            train_corrects = 0.0
            for data in tqdm(train_data_loader):
                X, y = data
                X = X.to(device) 
                y = y.to(device)
                optimizer.zero_grad()

                output = model(X)

                loss = loss_fn(output, y)

                loss.backward()
                optimizer.step()

                pred = torch.argmax(output, dim = 1)
                train_loss += loss.item() * (X.shape)[0]
                train_corrects += torch.sum(pred == y)
                del X
                del y
            
            train_epoch_loss = train_loss / len(train_data_loader.dataset)
            train_epoch_acc = 100* train_corrects.double() / len(train_data_loader.dataset)
            print('Train Epoch: {}, Acc: {:.6f}, Loss: {:.6f}'.format(epoch, train_epoch_acc, train_epoch_loss))
            
            if epoch == 0:
                id_folder = output_folder + str(wandb_id) + '/'
                if not os.path.exists(id_folder):
                    os.makedirs(id_folder)
        
           
            if epoch % 10 == 0:
                ckpt_file_path = '{}/ckpt_{}.pth.tar'.format(id_folder, str(epoch))
                if args.scheduler == 'no':
                    save_checkpoint(epoch, model, optimizer, None, loss, ckpt_file_path)
                else:
                    save_checkpoint(epoch, model, optimizer, scheduler, loss, ckpt_file_path)
            
            model.eval()
            with torch.no_grad():
                val_loss = 0.0
                val_corrects = 0.0
                for val_data in valid_data_loader:
                    val_X, val_y = val_data
                    val_X = val_X.to(device)
                    val_y = val_y.to(device)

                    val_output = model(val_X)
                    
                    val_loss_out = loss_fn(val_output, val_y)
                    val_loss += val_loss_out.item() * (val_X.shape)[0]
                    val_pred = torch.argmax(val_output, dim = 1)
                    val_corrects += torch.sum(val_pred == val_y)
                    del val_X
                    del val_y
                val_epoch_loss = val_loss / len(valid_data_loader.dataset)
                val_epoch_acc = 100 * val_corrects.double() / len(valid_data_loader.dataset)
            
            if args.scheduler == 'reduce':
                scheduler.step(val_epoch_loss)
            elif args.scheduler == 'step':
                scheduler.step()

            print('Valid Epoch: {}, Acc: {:.6f}'.format(epoch, val_epoch_acc))

            wandb.log({'epoch': epoch, 'train_acc' : train_epoch_acc, 'train_loss' : train_epoch_loss, 'val_acc' : val_epoch_acc, 'val_loss': val_epoch_loss})


def main(args):
    torch.cuda.empty_cache()
    
    global ckpt, device, ucf_folder, output_folder
    global epochs, workers, wandb_id

    config = {
      "batch_size" : args.batch_size,
      "resize_width" : args.resize_width,
      "resize_height" : args.resize_height,
      "crop_size" : args.crop_size,
      "clip_len" : args.clip_len,
      "optimizer_type": args.optimizer_type,
      "lr" : args.learning_rate,
      "step_size" : args.step_size,
      "sampling" : args.sampling,
      "scheduler" : args.scheduler,
      "normalize_type" : args.normalize_type
    }

    seed_everything()

    # import pdb;pdb.set_trace()
    train_dataset = UCF101Dataset(ucf_folder = ucf_folder, split= 'train', split_num = [1], resize_width = args.resize_width, resize_height = args.resize_height, crop_size = args.crop_size, clip_len = args.clip_len, sampling = args.sampling, normalize_type = args.normalize_type)
    valid_dataset = UCF101Dataset(ucf_folder = ucf_folder, split= 'test', split_num = [1], resize_width = args.resize_width, resize_height = args.resize_height, crop_size = args.crop_size, clip_len = args.clip_len, sampling = args.sampling, normalize_type = args.normalize_type)
    
    check_dataset(train_dataset, valid_dataset)
    train_data_loader = DataLoader(train_dataset, batch_size = args.batch_size, shuffle = True, collate_fn = collate_wrapper, num_workers=workers, worker_init_fn  = seed_worker, pin_memory=True, drop_last = True)
    valid_data_loader = DataLoader(valid_dataset, batch_size = args.batch_size, shuffle = False, collate_fn = collate_wrapper, num_workers=workers, worker_init_fn  = seed_worker, pin_memory=True, drop_last = False)
    
    if ckpt is None:
        seed_everything()
        model = C3DNet(num_classes = 101)
        wandb.init(id = wandb_id, resume = "allow", project= 'c3d', config = config, entity="uhhyunjoo")
    else:
        checkpoint = torch.load(ckpt)
        model = C3DNet(num_classes = 101)
        optimizer = optim.SGD(model.parameters(), lr = args.learning_rate, momentum = 0.9, weight_decay = 5e-4)
        optimizer.load_state_dict(checkpoint['optimizer'])
        epoch = checkpoint['epoch']
        loss = checkpoint['loss']

        model.load_state_dict(torch.load(ckpt))


    
    train_and_val(model, train_data_loader, valid_data_loader)

def check_dataset(train_dataset, valid_dataset):
    train_set = train_dataset.video_list
    valid_set = valid_dataset.video_list

    try :
        len(set(train_set + valid_set)) == len(train_set) + len(valid_set)
        print('Dataset : ok')
    except :
        print('train: {}, test : {}, set : {}'.format(len(train_set), len(valid_set), len(set(train_set + valid_set))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Train C3D with UCF101')

    parser.add_argument('--batch_size', default= 20, type=int)
    parser.add_argument('--resize_width', default = 171, type=int)
    parser.add_argument('--resize_height', default = 128, type=int)
    parser.add_argument('--crop_size', default = 112, type=int)
    parser.add_argument('--clip_len', default = 16, type=int)
    parser.add_argument('--optimizer_type', default='SGD', type=str, choices=['SGD', 'Adam', 'SGD_params'])
    
    parser.add_argument('--learning_rate', default=0.005, type=float)
    parser.add_argument('--step_size', default=20, type=int)
    parser.add_argument('--scheduler', default = 'no', type = str, choices = ['step', 'reduce', 'no'])

    parser.add_argument('--sampling', default='uniform_random', type=str, choices=['freq4_all_center', 'freq4_all_random', 'uniform_center', 'uniform_random'])
    parser.add_argument('--normalize_type', default = 'imagenet', type = str, choices = ['imagenet', 'ucf101'])

    args = parser.parse_args()
    main(args)