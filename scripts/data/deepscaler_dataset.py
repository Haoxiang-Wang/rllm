"""Script to prepare DeepScaler training and test datasets.

This script processes math problem datasets into a standardized format for training
and testing DeepScaler models. It loads problems from specified datasets, adds
instruction prompts, and saves the processed data as parquet files.
"""

import argparse
import os
from typing import Any

import pandas as pd

import rllm
from rllm.data.dataset_types import TestDataset, TrainDataset
from rllm.data.utils import load_dataset
from verl.utils.hdfs_io import copy, makedirs
from verl.utils.reward_score.math import last_boxed_only_string, remove_boxed

RLLM_PATH = os.path.dirname(os.path.dirname(rllm.__file__))


def extract_solution(solution_str: str) -> str:
    """Extract the final boxed solution from a solution string.

    Args:
        solution_str: Raw solution string that may contain multiple boxed answers

    Returns:
        The final boxed answer with box notation removed
    """
    return remove_boxed(last_boxed_only_string(solution_str))


def make_map_fn(split: str):
    """Create a mapping function to process dataset examples.

    Args:
        split: Dataset split name ('train' or 'test')

    Returns:
        Function that processes individual dataset examples
    """

    def process_fn(example: dict[str, Any], idx: int, instruction: str = None) -> dict[str, Any] | None:
        question = example.pop("problem")

        if instruction is None:
            instruction = "Let's think step by step and output the final answer within \\boxed{}."

        answer = example.pop("answer")

        data = {
            "data_source": "",
            "prompt": [{"role": "user", "content": f"{question} {instruction}"}],
            "ability": "math",
            "reward_model": {"style": "rule", "ground_truth": answer},
            "extra_info": {
                "split": split,
                "index": idx,
                "task": {"question": question, "ground_truth": answer},
            },
            "task": {"question": question, "ground_truth": answer},
            "uid": idx,
        }
        return data

    return process_fn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process datasets for DeepScaler training")
    parser.add_argument("--local_dir", default=os.path.join(RLLM_PATH, "data"), help="Local directory to save processed datasets")
    parser.add_argument("--hdfs_dir", default=None, help="Optional HDFS directory to copy datasets to")
    args = parser.parse_args()

    local_dir = args.local_dir
    hdfs_dir = args.hdfs_dir

    # Make local directory if it doesn't exist
    makedirs(local_dir, exist_ok=True)

    # Initialize datasets
    train_datasets = [TrainDataset.Math.DEEPSCALER]
    train_dataset = load_dataset(train_datasets[0])
    test_datasets = [TestDataset.Math.AIME, TestDataset.Math.AMC, TestDataset.Math.MATH, TestDataset.Math.MINERVA, TestDataset.Math.OLYMPIAD_BENCH]

    test_datasets_data = [load_dataset(d) for d in test_datasets]

    # Process training data
    train_data: list[dict[str, Any]] = []
    process_fn = make_map_fn("train")
    for idx, example in enumerate(train_dataset):
        processed_example = process_fn(example, idx)
        if processed_example is not None:
            train_data.append(processed_example)

    # Process and save each test dataset separately
    for test_dataset, test_data_list in zip(test_datasets, test_datasets_data, strict=False):
        test_data: list[dict[str, Any]] = []
        process_fn = make_map_fn("test")
        for idx, example in enumerate(test_data_list):
            processed_example = process_fn(example, idx)
            if processed_example is not None:
                test_data.append(processed_example)

        dataset_name = test_dataset.value.lower()
        test_df = pd.DataFrame(test_data)
        test_df.to_parquet(os.path.join(local_dir, f"{dataset_name}.parquet"))
        print(f"{test_dataset.value} test data size:", len(test_data))

    # Save training dataset
    print("Train data size:", len(train_data))
    train_df = pd.DataFrame(train_data)
    train_df.to_parquet(os.path.join(local_dir, "train.parquet"))

    # Optionally copy to HDFS
    if hdfs_dir is not None:
        makedirs(hdfs_dir)
        copy(src=local_dir, dst=hdfs_dir)
