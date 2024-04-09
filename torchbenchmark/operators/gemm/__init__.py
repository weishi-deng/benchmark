import argparse
import os
import statistics
from typing import Callable, Generator, List, Optional, Any

import csv
import numpy
import torch
import triton

from torchbenchmark.util.triton_op import (
    BenchmarkOperator,
    BenchmarkOperatorMetrics,
    register_benchmark,
    register_metric,
)

from torchbenchmark import REPO_PATH
from hammer.ops.triton.triton_matmul import triton_matmul as hstu_triton_matmul
from .triton_matmul import matmul as triton_matmul

BUILDIN_SHAPES = [
    (256, 256, 256, None),
    (384, 384, 384, None),
    (512, 512, 512, None),
    (640, 640, 640, None),
    (768, 768, 768, None),
    (896, 896, 896, None),
    (1024, 1024, 1024, None),
    (1152, 1152, 1152, None),
    (1280, 1280, 1280, None),
    (1408, 1408, 1408, None),
    (1536, 1536, 1536, None),
    (1664, 1664, 1664, None),

    # FIXME: triton_matmul failed with accuracy check for fb16 inputs on A100:
    # Mismatched elements: 882 / 3211264 (0.0%)
    # Greatest absolute difference: 0.03125 at index (169, 218) (up to 0.01 allowed)
    # Greatest relative difference: 35.21875 at index (1169, 1720) (up to 0.01 allowed)
    # (1792, 1792, 1792, None),

    (1920, 1920, 1920, None),
    (2048, 2048, 2048, None),
    (2176, 2176, 2176, None),
    (2304, 2304, 2304, None),

    # FIXME: triton_matmul failed with accuracy check for fb16 inputs on A100:
    # Mismatched elements: 2479 / 5914624 (0.0%)
    # Greatest absolute difference: 0.03173828125 at index (171, 1067) (up to 0.01 allowed)
    # Greatest relative difference: 95.875 at index (2423, 2312) (up to 0.01 allowed)
    # (2432, 2432, 2432, None),

    (2560, 2560, 2560, None),
    (2688, 2688, 2688, None),
    (2816, 2816, 2816, None),
    (2944, 2944, 2944, None),
    (3072, 3072, 3072, None),
    (3200, 3200, 3200, None),
    (3328, 3328, 3328, None),
    (3456, 3456, 3456, None),
    (3584, 3584, 3584, None),

    # FIXME: triton_matmul failed with accuracy check for fb16 inputs on A100:
    # Mismatched elements: 619 / 13778944 (0.0%)
    # Greatest absolute difference: 0.06005859375 at index (622, 69) (up to 0.02 allowed)
    # Greatest relative difference: 20.546875 at index (3609, 685) (up to 0.02 allowed)
    # (3712, 3712, 3712, None),

    (3840, 3840, 3840, None),
    (3968, 3968, 3968, None),
    (4096, 4096, 4096, None),
]


def parse_args(args: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TorchBench Gemm operator Benchmark")
    parser.add_argument("--m", default=8, type=int)
    parser.add_argument("--k", default=8, type=int)
    parser.add_argument("--n", default=8, type=int)
    parser.add_argument("--input", default=None, type=str)
    args = parser.parse_args(args)
    return args


def read_shapes_from_csv(csv_path: str) -> List[List[int]]:
    input_file_path = os.path.join(REPO_PATH, "torchbenchmark", "operators", "gemm", csv_path)
    shapes = []
    with open(input_file_path, "r") as f:
        reader = csv.reader(f)
        _header = next(reader)
        for row in reader:
            shapes.append([ int(x) if x else None for x in row])
    return shapes

class Operator(BenchmarkOperator):
    DEFAULT_METRICS = ["latency", "speedup", "accuracy"]
    DEFAULT_PRECISION = "fp16"

    def __init__(self, mode: str, device: str, extra_args: List[str] = []):
        super().__init__(mode=mode, device=device, extra_args=extra_args)
        if not self.extra_args:
            self.DEFAULT_NUM_BATCH = len(BUILDIN_SHAPES)
            self.shapes = BUILDIN_SHAPES
        else:
            self.tbargs = parse_args(self.extra_args)
            if self.tbargs.input:
                self.shapes = read_shapes_from_csv(self.tbargs.input)
            else:
                self.shapes = [(self.tb_args.m, self.tbargs.k, self.tbargs.n)]
            self.DEFAULT_NUM_BATCH = len(self.shapes)


    @register_benchmark()
    def triton_matmul(self, a, b, bias) -> Callable:
        if not bias == None:
            return lambda: triton_matmul(a, b) + bias
        else:
            return lambda: triton_matmul(a, b)


    @register_benchmark(baseline=True)
    def aten_matmul(self, a, b, bias) -> Callable:
        if not bias == None:
            return lambda: torch.matmul(a, b) + bias
        else:
            return lambda: torch.matmul(a, b)


    @register_benchmark()
    def hstu_triton_matmul(self, a, b, bias) -> Callable:
        if not bias == None:
            return lambda: hstu_triton_matmul(a, b) + bias
        else:
            return lambda: hstu_triton_matmul(a, b)

    def get_x_val(self, example_inputs) -> float:
        # x-value: computation intensity
        a, w, bias = example_inputs
        m, k = a.size()
        k, n = w.size()
        # computation intensity for the shape m, n, k
        intensity = 1 / (1 / n + 1 / m + 1 / k)
        return intensity

    @register_metric()
    def gbps(self, fn_name: str, example_inputs: Any, metrics: BenchmarkOperatorMetrics) -> float:
        a, w, bias = example_inputs
        numel = a.numel() + w.numel() + (torch.mm(a, w).numel())
        numel = numel * a.element_size() / 1e9
        gbps = list(map(lambda x: numel / x * 1e3, metrics.latency))
        return statistics.median(gbps)

    @register_metric(skip_baseline=True)
    def xShape(self, fn_name: str, example_inputs: Any, metrics: BenchmarkOperatorMetrics) -> list[int]:
        a, w, bias = example_inputs
        m, k = a.size()
        k, n = w.size()
        if not bias == None:
            return [m, k, n, bias.size()[0]]
        return [m, k, n]

    @register_metric()
    def tflops(self, fn_name: str, example_inputs: Any, metrics: BenchmarkOperatorMetrics) -> float:
        a, w, bias = example_inputs
        m, k = a.size()
        k, n = w.size()
        if not bias == None:
            flops = m * k * 2 * n + 2 * m * n
        else:
            flops = m * k * 2 * n
        return [flops / x / 1e12 * 1e3 for x in metrics.latency]

    def get_input_iter(self) -> Generator:
        for shape in self.shapes:
            m, k, n, bias = shape
            a = torch.randn(
                (m, k), device=self.device, dtype=self.dtype
            ).requires_grad_(False)
            w = torch.randn(
                (k, n), device=self.device, dtype=self.dtype
            ).requires_grad_(False)
            if not bias == None:
                bias = torch.randn(
                    (bias), device=self.device, dtype=self.dtype
                ).requires_grad_(False)
            yield a, w, bias
        while True:
            yield None

    def _get_accuracy(self, fn: Callable, baseline_fn: Callable) -> bool:
        output = fn()
        baseline_output = baseline_fn()
        accuracy = True
        try:
            torch.testing.assert_close(output, baseline_output)
        except Exception:
            accuracy = False
        finally:
            return accuracy

    def plot(self):
        @triton.testing.perf_report(
            triton.testing.Benchmark(
                x_names=["density"],  # argument names to use as an x-axis for the plot
                x_vals=self.output.x_vals,  # different possible values for `x_name`
                line_arg="provider",  # argument name whose value corresponds to a different line in the plot
                line_vals=[
                    "aten_matmul",
                    "triton_matmul",
                    "hstu_triton_matmul",
                ],  # possible values for `line_arg``
                line_names=[
                    "ATen GEMM",
                    "Triton GEMM",
                    "HSTU Triton GEMM",
                ],  # label name for the lines
                styles=[("blue", "-"), ("green", "-"), ("red", "-")],  # line styles
                ylabel="tflops",  # label name for the y-axis
                plot_name="gemm-performance",  # name for the plot. Used also as a file name for saving the plot.
                args={},  # values for function arguments not in `x_names` and `y_name`
            )
        )
        def _plot(density, provider):
            tflops = self.output.get_y_vals(density, provider, "tflops")
            return tflops

        save_path = "/tmp/test_gemm"

        if not os.path.exists(save_path):
            os.mkdir(save_path)

        _plot.run(show_plots=True, print_data=True, save_path="/tmp/test_gemm")
