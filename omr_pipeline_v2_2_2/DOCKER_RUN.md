# Running the OMR Pipeline with Docker

## Prerequisites

Make sure you have **Docker** and **Docker Compose** installed:

```bash
docker --version        # e.g. Docker version 24.x
docker compose version  # e.g. Docker Compose version v2.x
```

---

## Step 1 — Build the image

Run this once (or whenever the code or dependencies change):

```bash
cd /path/to/omr_pipeline_v2_2
docker build -t omr-pipeline .
```

> The first build takes ~5–10 minutes (downloads Ubuntu packages + Python wheels).
> Subsequent builds are fast thanks to Docker layer caching.

---

## Step 2 — Allow GUI access (run once per login session)

Since the pipeline has a Tkinter/DS9 GUI, Docker needs permission to draw on your screen:

```bash
xhost +local:docker
```

To undo this after you're done:
```bash
xhost -local:docker
```

---

## Step 3 — Run the pipeline

### Option A — With Docker Compose (recommended)

Edit `docker-compose.yml` to set the path to your FITS data:
```yaml
volumes:
  - /home/luciferat022/Documents/GitHub/VBO_Data_Reduction_Pipeline:/data:rw
```

Then run:
```bash
docker compose up
```

### Option B — With plain `docker run`

```bash
docker run --rm -it \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /path/to/your/fits/data:/data \
  --network host \
  omr-pipeline
```

Replace `/path/to/your/fits/data` with the actual directory containing your observation nights (e.g. `08mar2025_manual`, etc.).

---

## Step 4 — Pointing the pipeline at your data

Inside the container, your data is mounted at `/data`. When the pipeline prompts you to select a directory, navigate to `/data/`.

---

## Troubleshooting

### GUI doesn't open / "cannot open display"
```bash
# Make sure you ran xhost first:
xhost +local:docker
# And that DISPLAY is set:
echo $DISPLAY    # should show something like :1
```

### DS9 doesn't connect (pyds9 error)
The container uses `--network host` so DS9 inside the container can talk to itself via XPA. If DS9 still fails, try launching it manually first inside the container:
```bash
docker exec -it omr_pipeline ds9 &
```

### Import errors on first run
```bash
# Verify all packages installed correctly:
docker run --rm omr-pipeline python3 -c "import pyraf, astropy, scipy, matplotlib, pyds9; print('All OK')"
```

### IRAF "login.cl not found" error
PyRAF auto-generates `login.cl` in the working directory. The container's WORKDIR is `/app` which is writable, so this should be handled automatically. If it persists:
```bash
docker exec -it omr_pipeline bash -c "cd /app && python3 -m pyraf"
```

---

## Updating dependencies

If you add a new package to your environment:
```bash
# On your machine:
/home/luciferat022/iraf_work/.venv/bin/pip freeze > requirements.txt
# Then rebuild:
docker build -t omr-pipeline .
```
