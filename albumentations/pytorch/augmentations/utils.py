import cv2
import torch

from functools import wraps


MAX_VALUES_BY_DTYPE = {torch.uint8: 255, torch.float32: 1.0, torch.float64: 1.0}
OPENCV_TO_TORCH_INTERPOLATION = {
    cv2.INTER_LINEAR: "bilinear",
    cv2.INTER_NEAREST: "nearest",
    cv2.INTER_AREA: "area",
    cv2.INTER_CUBIC: "cicubic",
}
OPENCV_TO_TORCH_BORDER = {
    cv2.BORDER_CONSTANT: "zeros",
    cv2.BORDER_REPLICATE: "border",
    cv2.BORDER_REFLECT: "reflection",
    cv2.BORDER_REFLECT101: "reflection",
    cv2.BORDER_REFLECT_101: "reflection",
}


def grayscale_to_rgb(image):
    assert image.size(0) <= 3, "Supports only rgb and grayscale images."

    if image.size(0) == 3:
        return image

    return torch.cat([image] * 3)


def rgb_image(func):
    @wraps(func)
    def wrapped_function(img, *args, **kwargs):
        img = grayscale_to_rgb(img)
        result = func(img, *args, **kwargs)
        return result

    return wrapped_function


def is_rgb_image(image):
    return image.size(0) == 3


def preserve_shape(func):
    """
    Preserve shape of the image

    """

    @wraps(func)
    def wrapped_function(img, *args, **kwargs):
        shape = img.shape
        img = func(img, *args, **kwargs)
        img = img.view(*shape)
        return img

    return wrapped_function


def on_float_image(func):
    @wraps(func)
    def wrapped_function(img, *args, **kwargs):
        if img.dtype != torch.uint8:
            return func(img, *args, **kwargs)

        tmp = img.to(torch.float32) / 255.0
        result = func(tmp, *args, **kwargs)
        result = torch.clamp(torch.round(result * 255.0), 0, 255).to(img.dtype)
        return result

    return wrapped_function


def clip(img, dtype, maxval):
    return torch.clamp(img, 0, maxval).type(dtype)


def clipped(func):
    @wraps(func)
    def wrapped_function(img, *args, **kwargs):
        dtype = img.dtype
        maxval = MAX_VALUES_BY_DTYPE.get(dtype, 1.0)
        return clip(func(img, *args, **kwargs), dtype, maxval)

    return wrapped_function


def on_4d_image(dtype=None):
    def callable(func):
        @wraps(func)
        def wrapped_function(img, *args, **kwargs):
            old_dtype = img.dtype
            if dtype is not None:
                img = img.to(dtype)

            shape_len = len(img.shape)
            if shape_len < 3:
                img = img.view(1, 1, *img.shape)
            elif shape_len < 4:
                img = img.view(1, *img.shape)

            result = func(img, *args, **kwargs)
            result = result.view(*result.shape[-shape_len:])

            if old_dtype is not None:
                result = result.to(old_dtype)

            return result

        return wrapped_function

    return callable


def get_interpolation_mode(mode):
    if not isinstance(mode, str):
        return OPENCV_TO_TORCH_INTERPOLATION[mode]

    return mode


def get_border_mode(mode):
    if not isinstance(mode, str):
        return OPENCV_TO_TORCH_BORDER[mode]

    return mode


def on_3d_image(func):
    @wraps(func)
    def wrapped_function(img, *args, **kwargs):
        shape_len = len(img.shape)
        if shape_len < 3:
            img = img.view(1, *img.shape)
        result = func(img, *args, **kwargs)
        result = result.view(result.shape[-shape_len:])
        return result

    return wrapped_function
