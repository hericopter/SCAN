"""solver.py"""

import warnings
warnings.filterwarnings("ignore")

import os
from abc import ABC, abstractmethod
from tqdm import tqdm
import visdom
import random
from PIL import Image, ImageDraw
import math
import numpy as np

import torch
import torch.optim as optim
from torchvision.utils import make_grid, save_image
from torchvision import transforms

from utils import cuda, grid2gif
from model import BetaVAE_H_net, BetaVAE_B_net, DAE_net, SCAN_net
from dataset import return_data

#---------------------------------NEW CLASS-------------------------------------#
class Solver(ABC):
    def __init__(self, args, require_attr=False, nc=None):
        self.global_iter = 0
        self.args = args

        if nc is None:
            if args.dataset.lower() == 'dsprites':
                self.nc = 1
                self.decoder_dist = 'bernoulli'
            elif args.dataset.lower() == '3dchairs':
                self.nc = 3
                self.decoder_dist = 'gaussian'
            elif args.dataset.lower() == 'celeba':
                self.nc = 3
                self.decoder_dist = 'gaussian'
            else:
                raise NotImplementedError
        else:
            self.nc = nc

        self.output_dir = os.path.join(args.root_dir, self.env_name, args.output_dir)
        self.ckpt_dir = os.path.join(args.root_dir, self.env_name, args.ckpt_dir)

        if not os.path.exists(self.ckpt_dir):
            os.makedirs(self.ckpt_dir, exist_ok=True)
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        if self.args.vis_on:
            self.vis = visdom.Visdom(port=self.args.vis_port)
        self.gather = DataGather()
        self.net = cuda(self.model(self.z_dim, self.nc), self.args.cuda)
        self.optim = optim.Adam(self.net.parameters(), lr=self.args.lr,
                               betas=(self.args.beta1, self.args.beta2), eps=self.args.epsilon)
        self.load_checkpoint(self.args.ckpt_name)
        self.data_loader = return_data(self.args, require_attr)

    def prepare_training(self):
        pass
    @abstractmethod
    def training_process(self, x):
        pass
    @abstractmethod
    def get_win_states(self):
        pass
    @abstractmethod
    def load_win_states(self):
        pass

    def train(self):
        self.net_mode(train=True)
        self.prepare_training()

        self.pbar = tqdm(total=self.args.max_iter)
        self.pbar.update(self.global_iter)
        while self.global_iter < self.args.max_iter:
            for x in self.data_loader:
                self.global_iter += 1
                self.pbar.update(1)

                loss = self.training_process(x)
                self.optim.zero_grad()
                loss.backward()
                self.optim.step()

                if self.global_iter%self.args.display_save_step == 0:
                    self.save_checkpoint(self.get_win_states(), str(self.global_iter))
                    self.save_checkpoint(self.get_win_states(), 'last')
                    self.pbar.write('Saved checkpoint(iter:{})'.format(self.global_iter))

        self.pbar.write("[Training Finished]")
        self.pbar.close()

    def vis_display(self, image_set, traverse=True):
        if self.args.vis_on:
            for image in image_set:
                self.gather.insert(images=image.data)
            self.vis_reconstruction()
            self.vis_lines()
            self.gather.flush()

        if (self.args.vis_on or self.args.save_output) and traverse:
            self.vis_traverse()
    def vis_reconstruction(self):
        self.net_mode(train=False)
        x = self.gather.data['images'][0][:100]
        x = make_grid(x, normalize=True)
        x_recon = self.gather.data['images'][1][:100]
        x_recon = make_grid(x_recon, normalize=True)
        images = torch.stack([x, x_recon], dim=0).cpu()
        self.vis.images(images, env=self.env_name+'_reconstruction',
                        opts=dict(title=str(self.global_iter)), nrow=10)
        self.net_mode(train=True)

    def update_win(self, Y, win, legend, title):
        iters = torch.Tensor(self.gather.data['iter'])
        opts = dict( width=400, height=400, legend=legend, xlabel='iteration', title=title,)
        if win is None:
            return self.vis.line(X=iters, Y=Y, env=self.env_name+'_lines', opts=opts)
        else:
            return self.vis.line(X=iters, Y=Y, env=self.env_name+'_lines', win=win, update='append', opts=opts)
    def net_mode(self, train):
        if not isinstance(train, bool):
            raise('Only bool type is supported. True or False')
        if train:
            self.net.train()
        else:
            self.net.eval()

    def save_checkpoint(self, win_states, filename, silent=True):
        states = {'iter': self.global_iter,
                  'win_states': win_states,
                  'net_states': self.net.state_dict(),
                  'optim_states': self.optim.state_dict(),}

        file_path = os.path.join(self.ckpt_dir, filename)
        with open(file_path, mode='wb+') as f:
            torch.save(states, f)
        if not silent:
            print("=> saved checkpoint '{}' (iter {})".format(file_path, self.global_iter))
    def load_checkpoint(self, filename):
        file_path = os.path.join(self.ckpt_dir, filename)
        if os.path.isfile(file_path):
            checkpoint = torch.load(file_path)
            self.global_iter = checkpoint['iter']
            self.load_win_states(checkpoint['win_states'])
            self.net.load_state_dict(checkpoint['net_states'])
            self.optim.load_state_dict(checkpoint['optim_states'])
            print("=> loaded checkpoint '{} (iter {})'".format(file_path, self.global_iter))
        else:
            print("=> no checkpoint found at '{}'".format(file_path))
            keys = ['lines', 'reconstruction', 'traverse', 'img2sym', 'sym2img']
            for key in keys:
                env_name = self.env_name + '_' + key
                self.vis.delete_env(env_name)
    def tensor(self, tensor, requires_grad=True):
        return cuda(torch.tensor(tensor, dtype=torch.float32, requires_grad=requires_grad), self.args.cuda)

#---------------------------------NEW CLASS-------------------------------------#
class super_beta_VAE(Solver):
    def __init__(self, args):
        if args.model == 'H':
            self.model = BetaVAE_H_net
        elif args.model == 'B':
            self.model = BetaVAE_B_net
        else:
            raise NotImplementedError('only support model H or B')
        self.z_dim = args.beta_VAE_z_dim
        self.env_name = args.beta_VAE_env_name
        self.win_recon = None
        self.win_kld = None
        self.win_mu = None
        self.win_var = None

        super(super_beta_VAE, self).__init__(args)

    def prepare_training(self):
        self.args.C_max = self.tensor(torch.FloatTensor([self.args.C_max]))
    def recon_loss_funtion(self, x, x_recon):
        pass
    def training_process(self, x):
        x = self.tensor(x)
        x_recon, mu, logvar = self.net(x)
        recon_loss = self.recon_loss_function(x, x_recon)
        kld = kl_divergence(mu, logvar)

        if self.args.objective == 'H':
            loss = recon_loss + self.args.beta * kld
        elif self.args.objective == 'B':
            C = torch.clamp(self.args.C_max/self.args.C_stop_iter*self.global_iter, 0, self.args.C_max.data[0])
            loss = recon_loss + self.args.gamma * (kld - C).abs()

        if self.args.vis_on and self.global_iter % self.args.gather_step == 0:
            self.gather.insert(iter=self.global_iter,
                               mu=mu.mean(0).data, var=logvar.exp().mean(0).data,
                               recon_loss=recon_loss.data, kld=kld.data)

        if self.global_iter % self.args.display_save_step == 0:
            self.vis_display([x, self.visual(x_recon)])

        return loss

    def vis_lines(self):
        self.net_mode(train=False)
        def gather(name):
            return torch.stack(self.gather.data[name]).cpu()
        recon_losses = gather('recon_loss')
        mus = gather('mu')
        variances = gather('var')
        klds = gather('kld')

        legend = []
        for z_j in range(self.z_dim):
            legend.append('z_{}'.format(z_j))

        self.win_recon = self.update_win(recon_losses, self.win_recon, [''], 'reconstruction loss')
        self.win_kld = self.update_win(klds, self.win_kld, [''], 'kl divergence')
        self.win_mu = self.update_win(mus, self.win_mu, legend[:self.z_dim], 'posterior mean')
        self.win_var = self.update_win(variances, self.win_var, legend[:self.z_dim], 'posterior variance')

        self.net_mode(train=True)
    def vis_traverse(self, limit=3, inter=2/3, loc=-1):
        self.net_mode(train=False)

        decoder = self.net.decoder
        encoder = self.net.encoder
        interpolation = torch.arange(-limit, limit+0.1, inter)

        n_dsets = len(self.data_loader.dataset)
        rand_idx = random.randint(1, n_dsets-1)

        random_img = self.data_loader.dataset.__getitem__(rand_idx)
        random_img = self.tensor(random_img).unsqueeze(0)
        random_img_z = encoder(random_img)[:, :self.z_dim]

        random_z = self.tensor(torch.rand(1, self.z_dim))

        if self.args.dataset == 'dsprites':
            fixed_idx1 = 87040 # square
            fixed_idx2 = 332800 # ellipse
            fixed_idx3 = 578560 # heart

            fixed_img1 = self.data_loader.dataset.__getitem__(fixed_idx1)
            fixed_img1 = self.tensor(fixed_img1).unsqueeze(0)
            fixed_img_z1 = encoder(fixed_img1)[:, :self.z_dim]

            fixed_img2 = self.data_loader.dataset.__getitem__(fixed_idx2)
            fixed_img2 = self.tensor(fixed_img2).unsqueeze(0)
            fixed_img_z2 = encoder(fixed_img2)[:, :self.z_dim]

            fixed_img3 = self.data_loader.dataset.__getitem__(fixed_idx3)
            fixed_img3 = self.tensor(fixed_img3).unsqueeze(0)
            fixed_img_z3 = encoder(fixed_img3)[:, :self.z_dim]

            Z = {'fixed_square':fixed_img_z1, 'fixed_ellipse':fixed_img_z2,
                 'fixed_heart':fixed_img_z3, 'random_img':random_img_z}
        else:
            fixed_idx = 0
            fixed_img = self.data_loader.dataset.__getitem__(fixed_idx)
            fixed_img = self.tensor(fixed_img).unsqueeze(0)
            fixed_img_z = encoder(fixed_img)[:, :self.z_dim]

            Z = {'fixed_img':fixed_img_z, 'random_img':random_img_z, 'random_z':random_z}

        gifs = []
        for key in Z.keys():
            z_ori = Z[key]
            samples = []
            for row in range(self.z_dim):
                if loc != -1 and row != loc:
                    continue
                z = z_ori.clone()
                for val in interpolation:
                    z[:, row] = val
                    sample = self.visual(decoder(z)).data
                    samples.append(sample)
                    gifs.append(sample)
            samples = torch.cat(samples, dim=0).cpu()
            title = '{}_latent_traversal(iter:{})'.format(key, self.global_iter)

            self.vis.images(samples, env=self.env_name+'_traverse',
                            opts=dict(title=title), nrow=len(interpolation))

        if self.args.save_output:
            output_dir = os.path.join(self.args.output_dir, str(self.global_iter))
            os.makedirs(output_dir, exist_ok=True)
            gifs = torch.cat(gifs)
            gifs = gifs.view(len(Z), self.z_dim, len(interpolation), self.nc, 64, 64).transpose(1, 2)
            for i, key in enumerate(Z.keys()):
                for j, val in enumerate(interpolation):
                    save_image(tensor=gifs[i][j].cpu(),
                               filename=os.path.join(output_dir, '{}_{}.jpg'.format(key, j)),
                               nrow=self.z_dim, pad_value=1)

                grid2gif(os.path.join(output_dir, key+'*.jpg'),
                         os.path.join(output_dir, key+'.gif'), delay=10)

        self.net_mode(train=True)

    def get_win_states(self):
        return {'recon': self.win_recon,
                'kld': self.win_kld,
                'mu': self.win_mu,
                'var': self.win_var,}
    def load_win_states(self, win_states):
        self.win_recon = win_states['recon']
        self.win_kld = win_states['kld']
        self.win_var = win_states['var']
        self.win_mu = win_states['mu']


#---------------------------------NEW CLASS-------------------------------------#
class ori_beta_VAE(super_beta_VAE):
    def __init__(self, args):
        super(ori_beta_VAE, self).__init__(args)

    def recon_loss_function(self, x, x_recon):
        return reconstruction_loss(x, x_recon, self.decoder_dist)
    def visual(self, x):
        return x

#---------------------------------NEW CLASS-------------------------------------#
class beta_VAE(super_beta_VAE):
    def __init__(self, args):
        super(beta_VAE, self).__init__(args)

        DAE_solver = DAE(args)
        DAE_solver.net_mode(train=False)
        self.DAE_net = DAE_solver.net

    def recon_loss_function(self, x, x_recon):
        return reconstruction_loss(self.DAE_net._encode(x), self.DAE_net._encode(x_recon), self.decoder_dist)
    def visual(self, x):
        return self.DAE_net(x)

#---------------------------------NEW CLASS-------------------------------------#
class DAE(Solver):
    def __init__(self, args):
        self.win_recon = None
        self.model = DAE_net
        self.z_dim = args.DAE_z_dim
        self.env_name = args.DAE_env_name

        super(DAE, self).__init__(args)

    def prepare_training(self):
        pass
    def training_process(self, x):
        x = self.tensor(x)
        masked = random_occluding(x, [self.args.batch_size, self.nc, self.args.image_size, self.args.image_size], cuda_or_not=self.args.cuda)
        x_recon = self.net(masked)
        recon_loss = reconstruction_loss(x, x_recon, self.decoder_dist)
        loss = recon_loss

        if self.args.vis_on and self.global_iter % self.args.gather_step == 0:
            self.gather.insert(iter=self.global_iter, recon_loss=recon_loss.data)
        if self.global_iter % self.args.display_save_step == 0:
            self.pbar.write('[{}] recon_loss:{:.3f}'.format(self.global_iter, recon_loss.data[0]))
            self.vis_display([masked, x_recon], traverse=False)

        return loss

    def get_win_states(self):
        return {'recon': self.win_recon}
    def load_win_states(self, win_states):
        self.win_recon = win_states['recon']

    def vis_lines(self):
        self.net_mode(train=False)
        recon_losses = torch.stack(self.gather.data['recon_loss']).cpu()
        self.win_recon = self.update_win(recon_losses, self.win_recon, [''], 'reconstruction loss')
        self.net_mode(train=True)

#---------------------------------NEW CLASS-------------------------------------#
class SCAN(Solver):
    def __init__(self, args):
        self.model = SCAN_net
        self.z_dim = args.SCAN_z_dim
        self.env_name = args.SCAN_env_name
        self.win_recon = None
        self.win_kld = None
        self.win_relv = None
        self.win_mu = None
        self.win_var = None
        self.keys = None

        super(SCAN, self).__init__(args, require_attr=True, nc=40)

        beta_VAE_solver = beta_VAE(args)
        beta_VAE_solver.net_mode(train=False)
        self.beta_VAE_net = beta_VAE_solver.net
        self.DAE_net = beta_VAE_solver.DAE_net

    def training_process(self, data):
        [x, y, keys] = data
        x = self.tensor(x)
        y = self.tensor(y)
        if self.keys is None:
            self.keys = np.asarray(keys)[:, 0].tolist()
            self.n_key = len(self.keys)
        y_recon, mu_y, logvar_y = self.net(y)
        z_x = self.beta_VAE_net._encode(x)
        mu_x = z_x[:, :self.args.beta_VAE_z_dim]
        logvar_x = z_x[:, self.args.beta_VAE_z_dim:]

        recon_loss = reconstruction_loss(y, y_recon, 'bernoulli')
        kld = kl_divergence(mu_y, logvar_y)
        relv = dual_kl_divergence(mu_x, logvar_x, mu_y, logvar_y)
        loss = recon_loss + self.args.beta * kld + self.args.gamma * relv

        if self.args.vis_on and self.global_iter % self.args.gather_step == 0:
            self.gather.insert(iter=self.global_iter,
                               mu=mu_y.mean(0).data, var=logvar_y.exp().mean(0).data,
                               recon_loss=recon_loss.data, kld=kld.data, relv=relv.data)

        if self.global_iter % self.args.display_save_step == 0:
            self.vis_display([x, self.visual(y)])
        return loss

    def visual(self, y):
        return self.DAE_net(self.beta_VAE_net._decode(self.net._encode(y)))
    def get_win_states(self):
        return {'recon': self.win_recon,
                'kld': self.win_kld,
                'relv': self.win_relv,
                'mu': self.win_mu,
                'var': self.win_var,}
    def load_win_states(self, win_states):
        self.win_recon = win_states['recon']
        self.win_kld = win_states['kld']
        self.win_relv = win_states['relv']
        self.win_var = win_states['var']
        self.win_mu = win_states['mu']

    def vis_lines(self):
        self.net_mode(train=False)
        def gather(name):
            return torch.stack(self.gather.data[name]).cpu()
        recon_losses = gather('recon_loss')
        klds = gather('kld')
        relvs = gather('relv')
        mus = gather('mu')
        variances = gather('var')

        legend = []
        for z_j in range(self.z_dim):
            legend.append('z_{}'.format(z_j))

        self.win_recon = self.update_win(recon_losses, self.win_recon, [''], 'reconstruction loss')
        self.win_kld = self.update_win(klds, self.win_kld, [''], 'kl divergence')
        self.win_relv = self.update_win(relvs, self.win_relv, [''], 'relevance')
        self.win_mu = self.update_win(mus, self.win_mu, legend[:self.z_dim], 'posterior mean')
        self.win_var = self.update_win(variances, self.win_var, legend[:self.z_dim], 'posterior variance')

        self.net_mode(train=True)
    def vis_traverse(self, limit=3, inter=2/3, loc=-1, num_img2sym=16, num_sym2img=9):
        self.net_mode(train=False)
        n_dsets = self.data_loader.__len__()
        toimage = transforms.ToPILImage('RGB')
        interpolation = torch.arange(-limit, limit+0.1, inter)

        # img2sym
        images = []
        for i in range(num_img2sym):
            i_rand = random.randint(0, n_dsets)
            [image, attr, _] = self.data_loader.dataset.__getitem__(i_rand)
            y_x = self.net._decode(self.beta_VAE_net._encode(self.tensor(image.unsqueeze(0)))).cpu().squeeze(0)
            image = toimage(image)

            board = Image.new('RGB', (300, 100), 'white')
            board.paste(image, (18, 30))

            drawer = ImageDraw.Draw(board)
            attr_text = ''
            for i_key in range(self.n_key):
                if attr[i_key] >= 1.:
                    attr_text = attr_text + ' ' + self.keys[i_key]
            drawer.text((0, 5), attr_text, fill='black')

            y_x = y_x.tolist()
            sorted_y = y_x.copy()
            sorted_y.sort(reverse=True)
            sym_text = ''
            for i_key in range(5):
                index = y_x.index(sorted_y[i_key])
                sym_text = sym_text + '[{0}: {1:.3f}]\n'.format(self.keys[index], y_x[index])
            drawer.text((100, 20), sym_text, fill='black')

            images.append(transforms.ToTensor()(board))
        images = torch.stack(images, dim=0)
        self.vis.images(images, env=self.env_name+'_img2sym',
                        opts=dict(title='iter:{}'.format(self.global_iter)), nrow=int(math.sqrt(num_img2sym)))

        #sym2img
        images = []
        for i in range(self.n_key):
            random_ys = np.random.normal(size=[num_sym2img, self.nc])
            random_ys[:, i] = 1
            random_ys = self.tensor(random_ys)
            image_subset = self.DAE_net(self.beta_VAE_net._decode(self.net._encode(random_ys))).cpu().data
            nrow = int(math.sqrt(num_sym2img))
            image_subset = toimage(make_grid(image_subset, nrow=int(math.sqrt(num_sym2img))))
            image_subset.resize((nrow * self.args.image_size, nrow * self.args.image_size))

            board = Image.new('RGB', (nrow * self.args.image_size, nrow * self.args.image_size + 15), 'white') 
            board.paste(image_subset, (0, 15))
            drawer = ImageDraw.Draw(board)
            drawer.text((0, 0), self.keys[i], fill='black')

            images.append(transforms.ToTensor()(board))

        images = torch.stack(images, dim=0)
        self.vis.images(images, env=self.env_name+'_sym2img',
                        opts=dict(title='iter:{}'.format(self.global_iter)), nrow=5)

        #traverse
        images = []
        for i in range(self.n_key):
            n_traverse = len(list(interpolation))
            random_y = np.random.normal(size=[1, self.nc])
            def set_value(v):
                vector = random_y.copy()
                vector[0, i] = v
                return 
            random_ys = self.tensor(np.concatenate([set_value(j) for j in interpolation], axis=0))
            image_subset = self.DAE_net(self.beta_VAE_net._decode(self.net._encode(random_ys))).cpu().data
            image_row = toimage(make_grid(image_subset, nrow=1))
            image_row.resize((n_traverse * self.args.image_size, self.args.image_size))

            board = Image.new('RGB', (n_traverse * self.args.image_size, self.args.image_size + 15), 'white')
            board.paste(image_row, (0, 15))
            drawer = ImageDraw.Draw(board)
            drawer.text((0, 0), self.keys[i], fill='black')

            images.append(transforms.ToTensor()(board))

        images = torch.stack(images, dim=0)
        self.vis.images(images, env=self.env_name+'_sym2img',
                        opts=dict(title='iter:{}'.format(self.global_iter)), nrow=1)


        self.net_mode(train=True)



def reconstruction_loss(X, Y, distribution):
    batch_size = X.size(0)
    assert batch_size != 0

    if distribution == 'bernoulli':
        recon_loss = -(X * torch.log(Y) + (1 - X) * torch.log(1 - Y)).sum() / batch_size
    elif distribution == 'gaussian':
        recon_loss = ((X - Y) ** 2).sum() / batch_size
    else:
        recon_loss = None
    return recon_loss

def kl_divergence(mu, logvar):
    batch_size = mu.size(0)
    assert batch_size != 0
    if mu.data.ndimension() == 4:
        mu = mu.view(mu.size(0), mu.size(1))
    if logvar.data.ndimension() == 4:
        logvar = logvar.view(logvar.size(0), logvar.size(1))

    klds = -0.5*(1 + logvar - mu.pow(2) - logvar.exp())

    return klds.mean(0).sum()

def dual_kl_divergence(mu_x, logvar_x, mu_y, logvar_y):
    batch_size = mu_x.size(0)
    assert batch_size != 0

    if mu_x.data.ndimension() == 4:
        mu_x = mu_x.view(mu_x.size(0), mu_x.size(1))
    if logvar_x.data.ndimension() == 4:
        logvar_x = logvar_x.view(logvar_x.size(0), logvar_x.size(1))
    if mu_y.data.ndimension() == 4:
        mu_y = mu_y.view(mu_y.size(0), mu_y.size(1))
    if logvar_y.data.ndimension() == 4:
        logvar_y = logvar_y.view(logvar_y.size(0), logvar_y.size(1))

    var_x = logvar_x.exp()
    var_y = logvar_y.exp()
    klds = 0.5 * (-1 + var_x / var_y + ((mu_x - mu_y) ** 2) / var_y + logvar_y - logvar_x)

    return klds.mean(0).sum()

class DataGather(object):
    def __init__(self):
        self.data = self.get_empty_data_dict()

    def get_empty_data_dict(self):
        return dict(iter=[],
                    recon_loss=[],
                    kld=[],
                    relv=[],
                    mu=[],
                    var=[],
                    images=[],)

    def insert(self, **kwargs):
        for key in kwargs:
            self.data[key].append(kwargs[key])

    def flush(self):
        self.data = self.get_empty_data_dict()

def random_occluding(images, size, cuda_or_not=True):
    occluded = images.clone()
    (batch_size, nc, x, y) = size
    def random_mask():
        left = random.randint(0, x)
        right = random.randint(0, x)
        down = random.randint(0, y)
        up = random.randint(0, y)
        if left > right:
            left, right = right, left
        if down > up:
            down, up = up, down
        mask = torch.zeros([nc, x, y], dtype=torch.uint8)
        mask[:, left : right, down : up] = 1
        return mask

    masks = torch.stack([random_mask() for i in range(batch_size)])
    masks = cuda(masks, cuda_or_not)
    occluded.masked_fill_(masks, 0)
    return occluded

