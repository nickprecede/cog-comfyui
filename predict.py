from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import os
import json
import base64
import shutil
import tarfile
import zipfile
import mimetypes
from PIL import Image
from typing import List
from copy import deepcopy
from cog import BasePredictor, Input, Path
from comfyui import ComfyUI
from weights_downloader import WeightsDownloader
from cog_model_helpers import optimise_images
from config import config

# FastAPI app
app = FastAPI()

os.environ["DOWNLOAD_LATEST_WEIGHTS_MANIFEST"] = "true"
mimetypes.add_type("image/webp", ".webp")
OUTPUT_DIR = "/tmp/outputs"
INPUT_DIR = "/tmp/inputs"
COMFYUI_TEMP_OUTPUT_DIR = "ComfyUI/temp"
ALL_DIRECTORIES = [OUTPUT_DIR, INPUT_DIR, COMFYUI_TEMP_OUTPUT_DIR]

with open("examples/api_workflows/sd15_txt2img.json", "r") as file:
    EXAMPLE_WORKFLOW_JSON = file.read()


class ImageRequest(BaseModel):
    workflow_json: str
    input_file: str  # Image URL or base64 string
    return_temp_files: bool = False
    output_format: str = optimise_images.predict_output_format()
    output_quality: int = optimise_images.predict_output_quality()
    randomise_seeds: bool = True
    force_reset_cache: bool = False


class Predictor(BasePredictor):
    def setup(self, weights: str):
        if bool(weights):
            self.handle_user_weights(weights)

        self.comfyUI = ComfyUI("127.0.0.1:8188")

        if not self.comfyUI.is_server_running():
            self.comfyUI.start_server(OUTPUT_DIR, INPUT_DIR)

    def handle_user_weights(self, weights: str):
        print(f"Downloading user weights from: {weights}")
        WeightsDownloader.download("weights.tar", weights, config["USER_WEIGHTS_PATH"])
        for item in os.listdir(config["USER_WEIGHTS_PATH"]):
            source = os.path.join(config["USER_WEIGHTS_PATH"], item)
            destination = os.path.join(config["MODELS_PATH"], item)
            if os.path.isdir(source):
                if not os.path.exists(destination):
                    print(f"Moving {source} to {destination}")
                    shutil.move(source, destination)
                else:
                    for root, _, files in os.walk(source):
                        for file in files:
                            if not os.path.exists(os.path.join(destination, file)):
                                print(
                                    f"Moving {os.path.join(root, file)} to {destination}"
                                )
                                shutil.move(os.path.join(root, file), destination)
                            else:
                                print(
                                    f"Skipping {file} because it already exists in {destination}"
                                )

    def handle_input_file(self, input_file: Path):
        file_extension = self.get_file_extension(input_file)

        if file_extension == ".tar":
            with tarfile.open(input_file, "r") as tar:
                tar.extractall(INPUT_DIR)
        elif file_extension == ".zip":
            with zipfile.ZipFile(input_file, "r") as zip_ref:
                zip_ref.extractall(INPUT_DIR)
        elif file_extension in [".jpg", ".jpeg", ".png", ".webp"]:
            shutil.copy(input_file, os.path.join(INPUT_DIR, f"input{file_extension}"))
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")

        print("====================================")
        print(f"Inputs uploaded to {INPUT_DIR}:")
        self.comfyUI.get_files(INPUT_DIR)
        print("====================================")

    def get_file_extension(self, input_file: Path) -> str:
        file_extension = os.path.splitext(input_file)[1].lower()
        if not file_extension:
            with open(input_file, "rb") as f:
                file_signature = f.read(4)
            if file_signature.startswith(b"\x1f\x8b"):  # gzip signature
                file_extension = ".tar"
            elif file_signature.startswith(b"PK"):  # zip signature
                file_extension = ".zip"
            else:
                try:
                    with Image.open(input_file) as img:
                        file_extension = f".{img.format.lower()}"
                        print(f"Determined file type: {file_extension}")
                except Exception as e:
                    raise ValueError(
                        f"Unable to determine file type for: {input_file}, {e}"
                    )
        return file_extension

    def predict(
        self,
        workflow_json: str = Input(
            description="Your ComfyUI workflow as JSON. You must use the API version of your workflow. Get it from ComfyUI using ‘Save (API format)’. Instructions here: https://github.com/fofr/cog-comfyui",
            default="",
        ),
        input_file: Path = Input(
            description="Input image, tar or zip file. Read guidance on workflows and input files here: https://github.com/fofr/cog-comfyui. Alternatively, you can replace inputs with URLs in your JSON workflow and the model will download them.",
            default=None,
        ),
        return_temp_files: bool = Input(
            description="Return any temporary files, such as preprocessed controlnet images. Useful for debugging.",
            default=False,
        ),
        output_format: str = optimise_images.predict_output_format(),
        output_quality: int = optimise_images.predict_output_quality(),
        randomise_seeds: bool = Input(
            description="Automatically randomise seeds (seed, noise_seed, rand_seed)",
            default=True,
        ),
        force_reset_cache: bool = Input(
            description="Force reset the ComfyUI cache before running the workflow. Useful for debugging.",
            default=False,
        ),
    ) -> List[Path]:
        """Run a single prediction on the model"""
        self.comfyUI.cleanup(ALL_DIRECTORIES)

        if input_file:
            self.handle_input_file(input_file)

        wf = workflow_json
        if not isinstance(wf, dict):
            wf = json.loads(wf)
            wf_base = wf

        if 'prompt' in wf_base:
            wf_base = wf_base['prompt']

        wf_base = self.comfyUI.load_workflow(wf_base or EXAMPLE_WORKFLOW_JSON)

        self.comfyUI.connect()

        if force_reset_cache or not randomise_seeds:
            self.comfyUI.reset_execution_cache()

        if randomise_seeds:
            self.comfyUI.randomise_seeds(wf_base)

        self.comfyUI.run_workflow(wf, wf_base)

        output_directories = [OUTPUT_DIR]
        if return_temp_files:
            output_directories.append(COMFYUI_TEMP_OUTPUT_DIR)

        return optimise_images.optimise_image_files(
            output_format, output_quality, self.comfyUI.get_files(output_directories)
        )


@app.post("/predict")
async def predict(request: ImageRequest):
    """API endpoint for prediction."""
    predictor = Predictor()
    predictor.setup()
    try:
        output_files = predictor.predict(
            workflow_json=request.workflow_json,
            input_file=request.input_file,
            return_temp_files=request.return_temp_files,
            output_format=request.output_format,
            output_quality=request.output_quality,
            randomise_seeds=request.randomise_seeds,
            force_reset_cache=request.force_reset_cache
        )
        return {"outputs": [str(f) for f in output_files]}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    

@app.post("/pubsub/predict")
async def pubsub_predict(request: Request):
    """Pub/Sub endpoint for asynchronous predictions."""
    predictor = Predictor()
    predictor.setup()
    try:
        # Decode Pub/Sub message
        envelope = await request.json()
        pubsub_message = envelope.get("message", {})
        if "data" not in pubsub_message:
            return {"error": "No data in Pub/Sub message"}, 400

        # Decode and parse JSON data from Pub/Sub message
        data = json.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))

        # Extract parameters for prediction
        image_request = ImageRequest(**data)

        # Run the prediction
        output_files = predictor.predict(
            workflow_json=image_request.workflow_json,
            input_file=image_request.input_file,
            return_temp_files=image_request.return_temp_files,
            output_format=image_request.output_format,
            output_quality=image_request.output_quality,
            randomise_seeds=image_request.randomise_seeds,
            force_reset_cache=image_request.force_reset_cache
        )

        return {"outputs": [str(f) for f in output_files]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))