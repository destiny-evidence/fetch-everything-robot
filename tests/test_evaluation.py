import random
from pathlib import Path

import pytest

from fer.config import get_settings
from fer.data_models.metrics import EvaluationRunEntry
from fer.local.run import generate_study_collection_from_dois, prepare_processor
from fer.logger import logger

EVAL_DATASET_PATH = (
    Path(__file__).parent / "fixtures/evaluation_datasets/climate_and_health.txt"
)


@pytest.mark.eval
@pytest.mark.asyncio
async def test_random_pool_evaluation(tmp_path, eval_config):
    """
    Evaluate the PDF robot on a random sample of DOIs from papers relevant to climate and health.

    The seed of the random sample defaults to the current day, to enable debugging, but prevent overfitting.

    Random seed and sample size can be overriden by environment variables.
    """
    assert EVAL_DATASET_PATH.exists(), f"Master pool not found at {EVAL_DATASET_PATH}"

    with EVAL_DATASET_PATH.open() as f:
        all_dois = [line.strip() for line in f if line.strip()]

    assert len(all_dois) > 0, "The master pool DOI file is empty!"

    sample_size = min(eval_config["sample_size"], len(all_dois))

    random.seed(eval_config["seed"])
    sampled_dois = random.sample(all_dois, sample_size)
    logger.info(
        f"Sampled {sample_size} DOIs out of {len(all_dois)} for this evaluation run."
    )

    study_collection = generate_study_collection_from_dois(sampled_dois)

    settings = get_settings()
    processor = prepare_processor(settings, exclude_api=None)

    output_directory = tmp_path / "latest_run_output"
    output_directory.mkdir(parents=True, exist_ok=True)

    results = await processor.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
        input_study_collection=study_collection,
        output_directory=output_directory,
    )

    entry = EvaluationRunEntry.from_results(results, settings)
    entry.save()

    assert len(results) == len(study_collection.studies)
