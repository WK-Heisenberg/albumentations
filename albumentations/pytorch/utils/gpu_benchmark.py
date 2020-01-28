import albumentations as A
import albumentations.pytorch as ATorch

import os
import sys
import time
import torch
import numpy as np
from tqdm import tqdm


def _bench(n, img, mask, bboxes, transform, desc, file):
    s = time.time()
    for _ in tqdm(range(n), desc=desc, file=file):
        transform(image=img, bboxes=bboxes, mask=mask)
    e = time.time()
    return n / (e - s)


def _format_row(values, max_lengths):
    row = ""
    for value, length in zip(values, max_lengths):
        padding = " " * (length - len(value))
        row += f"| {padding}{value} "
    row += "|"
    return row


def results_to_pretty_string(results):
    cols = ["Shape", "CPU FPS", "GPU FPS"]
    cols_length = [len(i) for i in cols]

    shapes = []
    cpu_fps = []
    gpu_fps = []

    for result in results:
        shapes.append(str(result["shape"]))
        cpu_fps.append(f"{result['cpu_fps']:.2f}")
        gpu_fps.append(f"{result['gpu_fps']:.2f}")

        cols_length[0] = max(cols_length[0], len(shapes[-1]))
        cols_length[1] = max(cols_length[1], len(cpu_fps[-1]))
        cols_length[2] = max(cols_length[2], len(gpu_fps[-1]))

    results_string = _format_row(cols, cols_length) + "\n"
    results_string += _format_row(["-" * i for i in cols_length], cols_length) + "\n"

    for values in zip(shapes, cpu_fps, gpu_fps):
        results_string += _format_row(values, cols_length) + "\n"

    return results_string


def print_results(results):
    print(results_to_pretty_string(results))


def _gen_random_bboxes(shape):
    h, w = shape[:2]
    bboxes = []

    for _ in range(np.random.randint(1, 100)):
        x1 = np.random.randint(0, w - 2)
        y1 = np.random.randint(0, h - 2)
        x2 = np.random.randint(x1 + 1, w)
        y2 = np.random.randint(y1 + 1, h)
        bboxes.append([x1, y1, x2, y2, np.random.randint(100)])

    return bboxes


def gpu_benchmark(
    cpu_aug, gpu_aug, shapes, iterations, to_float_cpu=False, to_float_gpu=True, on_gpu_img=False, silent=False
):
    """Compare CPU and GPU transforms.

    Args:
        cpu_aug: CPU augmnetations.
        gpu_aug: GPU pytorch augmentations.
        shapes: Images shapes in `HWC` format.
        to_float_cpu: If `True` convert image to range [0, 1] before benchmarking.
        to_float_gpu: If `True` convert image to range [0, 1] before benchmarking.
        iterations(int, list): Number of iterations for each shape.
                               If length less then shapes, last value will be repeated.
        on_gpu_img: If `True`, image for GPU transform will be created on gpu
                    and image creation time will not be added to benchmark.
                    If `False` gpu_aug must be contains `ToTensorV2` transform.

    Examples:
        >>> cpu_aug = A.Compose([A.Normalize(0, 1), ATorch.ToTensorV2(device="cuda")])
        >>> gpu_aug = A.Compose([ATorch.ToTensorV2(device="cuda"), ATorch.NormalizeTorch(0, 1)])
        >>> shapes = [
        >>>     [2048, 2048, 3],
        >>>     [2560, 1440, 3],
        >>>     [3840, 2160, 3],
        >>>     [1920, 1080, 3],
        >>>     [1024, 1024, 3],
        >>>     [1280, 720, 3],
        >>>     [512, 512, 3],
        >>>     [256, 256, 3],
        >>>     [128, 128, 3],
        >>> ]
        >>> iterations = [100] * 3 + [1000]
        >>> results = gpu_benchmark(cpu_aug, gpu_aug, shapes, iterations, silent=False)

    """
    if silent:
        stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")

    cpu_aug.p = 1
    gpu_aug.p = 1
    cpu_aug = A.Compose(cpu_aug, bbox_params=A.BboxParams("pascal_voc"))
    gpu_aug = A.Compose(gpu_aug, bbox_params=A.BboxParams("pascal_voc"))

    print("Warming up: ", end="")
    s = time.time()
    if on_gpu_img:
        image = torch.rand([3, 100, 100], dtype=torch.float32, device="cuda")
        mask = torch.rand([100, 100], dtype=torch.float32, device="cuda")
    else:
        image = np.random.random([100, 100, 3]).astype(np.float32)
        mask = np.random.random([100, 100]).astype(np.float32)
    gpu_aug(image=image, mask=mask, bboxes=_gen_random_bboxes([100, 100]))
    print(time.time() - s, end="\n\n")

    if not hasattr(iterations, "__len__"):
        iterations = list(iterations) * len(shapes)
    elif len(iterations) < len(shapes):
        iterations = list(iterations)
        iterations += [iterations[-1]] * (len(shapes) - len(iterations))

    results = []

    for n, shape in zip(iterations, shapes):
        cpu_image = np.random.randint(0, 256, shape, dtype=np.uint8)
        gpu_image = cpu_image.copy()
        bboxes = _gen_random_bboxes(cpu_image.shape)
        cpu_mask = np.random.randint(0, 2, shape[:2], dtype=np.uint8)
        gpu_mask = cpu_mask.copy()

        if on_gpu_img:
            if len(gpu_image.shape) < 3:
                gpu_image.reshape(gpu_image.shape + (1,))
            gpu_image = torch.from_numpy(gpu_image.transpose(2, 0, 1)).to("cuda")
            gpu_mask = torch.from_numpy(gpu_mask).to("cuda")

        if to_float_cpu and cpu_image.dtype == np.uint8:
            cpu_image = cpu_image.astype(np.float32) / 255.0
            cpu_mask = cpu_mask.astype(np.float32)
        if to_float_gpu:
            if isinstance(gpu_image, np.ndarray) and gpu_image.dtype == np.uint8:
                gpu_image = gpu_image.astype(np.float32) / 255.0
                gpu_mask = gpu_mask.astype(np.float32)
            elif gpu_image.dtype == torch.uint8:
                gpu_image = gpu_image.float() / 255.0
                gpu_mask = gpu_mask.float()

        cpu_fps = _bench(
            n, cpu_image, cpu_mask, bboxes, cpu_aug, "CPU transforms. Shape: {}".format(shape), sys.stdout
        )
        gpu_fps = _bench(
            n, gpu_image, gpu_mask, bboxes, gpu_aug, "GPU transforms. Shape: {}".format(shape), sys.stdout
        )

        results.append({"shape": shape, "cpu_fps": cpu_fps, "gpu_fps": gpu_fps})

    if silent:
        sys.stdout = stdout
    else:
        print()
        print_results(results)
    return results


if __name__ == "__main__":
    cpu_aug = A.Compose([A.Normalize(0, 1), ATorch.ToTensorV2(device="cuda")])
    gpu_aug = A.Compose([ATorch.ToTensorV2(device="cuda"), ATorch.NormalizeTorch(0, 1)])

    shapes = [
        [3840, 2160, 3],
        [2048, 2048, 3],
        [2560, 1440, 3],
        [1920, 1080, 3],
        [1024, 1024, 3],
        [1280, 720, 3],
        [512, 512, 3],
        [256, 256, 3],
        [128, 128, 3],
    ]

    iterations = [100] * 3 + [1000]

    results = gpu_benchmark(cpu_aug, gpu_aug, shapes, iterations, to_float_gpu=False, silent=False)
