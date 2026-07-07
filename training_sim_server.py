import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from main import TrainingSimRequest, base_dir, images_dir, training_sim_calculate, training_sim_meta


app = FastAPI(title="Sweepy Training Sim")


def _public_file(name: str) -> Path:
    return base_dir / "public" / name


@app.get("/")
async def root():
    return await training_sim_page()


@app.get("/training-sim")
async def training_sim_page():
    path = _public_file("training_sim.html")
    if path.exists():
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="training_sim.html not found")


@app.get("/styles.css")
async def styles_css():
    path = _public_file("styles.css")
    if path.exists():
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="styles.css not found")


@app.get("/training_sim.css")
async def training_sim_css():
    path = _public_file("training_sim.css")
    if path.exists():
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="training_sim.css not found")


@app.get("/training_sim.js")
async def training_sim_js():
    path = _public_file("training_sim.js")
    if path.exists():
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="training_sim.js not found")


@app.get("/api/training-sim/meta")
async def standalone_training_sim_meta():
    return await training_sim_meta()


@app.post("/api/training-sim/calculate")
async def standalone_training_sim_calculate(req: TrainingSimRequest):
    return await training_sim_calculate(req)


@app.get("/api/images/{image_name}")
async def get_image(image_name: str):
    name_no_ext = image_name.split("?")[0].replace(".png", "")
    exact_path = images_dir / f"{name_no_ext}.png"
    if exact_path.exists():
        return FileResponse(exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    for fallback_id in ("100101", "10010", "10001"):
        fallback_path = images_dir / f"{fallback_id}.png"
        if fallback_path.exists():
            return FileResponse(fallback_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="Image not found")


if __name__ == "__main__":
    host = os.environ.get("SWEEPY_TRAINING_SIM_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("SWEEPY_TRAINING_SIM_PORT", "1818"))
    print("Sweepy Training Sim only; no game login/session is required.", flush=True)
    print(f"Access the Training Sim at: http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="error")
