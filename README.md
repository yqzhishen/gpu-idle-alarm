# GPU Idle Alarm
 Send an alarm email when your GPUs are idle for a long time. May be useful if you rent GPUs from cloud services to train AI models.

## Usage

1. Install dependencies with `pip install click nvidia-ml-py pyyaml` or `pip install -r requirements.txt`.
2. Prepare an email account, generate an authorization token and fill these values in `smtp.yaml`.
3. Run `python alarm.py`. For more configurations, run `python alarm.py --help`.
4. By default, the program will check your GPU utilization rates every 10 seconds and send an alarm email if some of the rates are below 20% for more than 30 minutes.

## Limitations

The program only supports tracking utilization rates of NVIDIA GPUs.
