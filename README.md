# SCAN
This is a pytorch reproduction of the paper [SCAN: Learning Hierarchical Compositional Visual Concepts, Higgins et al., ICLR 2018][SCAN]

This implementation is based on the [implementation][beta-VAE] of β-VAE.
The β-VAE model used here, however, is modified to utilize another DAE as reconstruction loss provider according to the paper.


## Usage

### Dependencies
```
python 3.6
pytorch 0.4
visdom
numpy
```

### Running

By default, the working environment setting is `/data/hc/SCAN/` in `main.py` `--root_dir`, which should be modified for your convenience.
This is directory is supposed to contain the dataset in `root_dir/dataset/`, and is where checkpoint files and output files will be saved.

Dataset preparation is the same as [here](https://github.com/1Konny/FactorVAE)

To initialize visdom:

    visdom -port 6059

To reproduce the results of SCAN, please run the three `.sh` files one by one:

    sh scripts/DAE.sh
    sh scripts/beta_VAE.sh
    sh scripts/SCAN.sh

The original [β-VAE commands][beta-VAE] are still supported, and examples of result reproducing commands can be found in `scripts/original-beta_VAE/`


## Selected Results

Here are the results on CelebA dataset. The performance is still to be imporved.
(To view results in full detail, please go to [this file](results/Results_in_detail.md) of `results/Results_in_detail.md`.)

### reconstruction

Left part: original images. Right part: reconstructed images based on description.

![reconstruction](results/SCAN/reconstruction.jpg)

### img2sym

In every card, columns shown from left to right are: 1. original image, 2. labels, 3. top predicted labels and probabilities.

![img2sym](results/SCAN/img2sym.jpeg)

### sym2img

Attributes other than the appointed ones are randomly sampled within {0, 1}. Here 25 of all 40 attributes are selected.

![sym2img](results/SCAN/selected_sym2img.jpeg)

### traversal

Traversal range is -3 ~ 3. Here 16 of all 40 attributes are selected.

![traversal](results/SCAN/selected_traversal.jpeg)


## Others

### Note

There is some sort of self-contradiction in the paper.

1. The reconstruction loss of β-VAE is said to be the square difference of only the DAE encoder net in its Section 4,
but in Appendix A.1 the loss is said to be between "the pixel space of DAE reconstructions".
This is mentioned in [this issue][issue], too.
In the code, I applied only the DAE encoder net.

2. Under equation(4) of the paper, the authors mentioned "to up-weight the forward KL term relative to the other terms in the cost function (e.g. λ = 1, β = 10)", which seems to be self-contradicting.
In the code, I adopted the setting in Appendix A.1, which is λ = 10, β = 1.

Up to now, I haven't implemented the recombination operator part.
This is partly because of lack of time, and partly because I mainly reproduced the CelebA experiment,
in which the paper didn't show the results of the recombination part, either.

I will try to implement this operator later, if necessary and time permitting.
However, I guess the preformance will not be satisfying, because the results of SCAN net on the CelebA dataset is already non-significant
(which is due to either the complexity of face data or the imperfectness of my code).

### Acknowledgement:

I've referred to [the issue][issue] mentioned above, and adopted its solution,
which is to use the DAE output rather the direct results of β-VAE to improve the visuality.

### Reference
1. Original paper: [SCAN: Learning Hierarchical Compositional Visual Concepts, Higgins et al., ICLR 2018][SCAN]
2. Github Repo: [Pytorch implementation of β-VAE][beta-VAE] by [1Konny](https://github.com/1Konny)

[SCAN]: https://arxiv.org/abs/1707.03389
[beta-VAE]: https://github.com/1Konny/Beta-VAE 
[issue]: https://github.com/miyosuda/scan/issues/1
