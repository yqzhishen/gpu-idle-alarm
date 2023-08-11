import pathlib
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

import click
import yaml
from pynvml import *

quiet_mode = False


def verbose(*args, **kwargs):
    if not quiet_mode:
        print(*args, **kwargs)


def get_utilization_rates(devices):
    try:
        nvmlInit()
        count = nvmlDeviceGetCount()
        utils = []
        if devices is None:
            devices = range(count)
        for i in devices:
            if i >= count:
                continue
            handle = nvmlDeviceGetHandleByIndex(i)
            utils.append({
                'index': i,
                'name': nvmlDeviceGetName(handle),
                'util': nvmlDeviceGetUtilizationRates(handle).gpu
            })
        return utils
    except NVMLError as e:
        verbose(e)
    finally:
        nvmlShutdown()


def smtp_connect(config):
    host = config['host']
    port = config['port']
    account = config['account']
    password = config['password']
    connection = smtplib.SMTP_SSL(host, port)
    connection.login(account, password)
    verbose(f'Connected to {host} successfully.')
    return connection


@click.command(help='Start alarm process for idle GPU detection.')
@click.option('--interval', type=int, default=10, show_default=True, metavar='SECONDS',
              help='Checking interval.')
@click.option('--duration', type=int, default=30, show_default=True, metavar='MINUTES',
              help='Duration for which any GPUs are idle before giving an alarm.')
@click.option('--threshold', type=int, default=20, show_default=True, metavar='RATE',
              help='GPU utilization threshold.')
@click.option('--devices', type=str, default='auto', show_default=True, metavar='ID,ID,...',
              help='Indexes of devices to ba tracked.')
@click.option('--config', type=str, metavar='PATH',
              help='Specify another SMTP configuration file other than smtp.yaml.')
@click.option('--quiet', is_flag=True,
              help='Use quiet mode (disable all logging).')
def main(interval, duration, threshold, devices, config, quiet):
    # check options
    global quiet_mode
    quiet_mode = quiet
    devices = sorted(set(int(i) for i in devices.split(','))) if devices != 'auto' else None
    config = pathlib.Path(__file__).parent / 'smtp.yaml' if config is None else pathlib.Path(config)
    with open(config, 'r', encoding='utf8') as f:
        config_dict = yaml.safe_load(f)
    if not config_dict.get('to'):
        config_dict['to'] = config_dict['account']

    last_check_time = time.time()
    idle_durations = []  # in seconds
    device_names = []

    def reset_history(info_seq):
        nonlocal idle_durations
        nonlocal device_names
        idle_durations = [0] * len(info_seq)
        device_names = [d['name'] for d in info_seq]

    def print_summary(info_seq):
        verbose(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
        if len(info_seq) == 0:
            verbose('No NVIDIA GPUs detected.')
        for j, info in enumerate(info_seq):
            index = info['index']
            name = info['name']
            util = info['util']
            timer_repr = time.strftime("%H:%M:%S", time.gmtime(idle_durations[j]))
            idle = '' if util >= threshold else f', idle for {timer_repr}'
            verbose(f'[{index}] {name}: {util}%{idle}')

    try:
        # connect to SMTP host
        verbose('Test connection...')
        connection = smtp_connect(config_dict)
        connection.quit()

        # get the first information
        rates = get_utilization_rates(devices)
        reset_history(rates)
        print_summary(rates)

        while True:
            # sleep for interval
            time.sleep(interval)
            # get utilization rates
            rates = get_utilization_rates(devices)
            # update time point
            this_check_time = time.time()
            real_interval = this_check_time - last_check_time
            last_check_time = this_check_time
            # check devices
            device_changed = len(rates) != len(device_names) or any(
                    name_old != name_new for name_old, name_new in zip(device_names, (d['name'] for d in rates))
            )
            if device_changed:
                verbose('Device changes detected - timers reset.')
                reset_history(rates)
                print_summary(rates)
                continue

            # update timers
            for i, rate in enumerate(d['util'] for d in rates):
                if rate >= threshold:
                    # reset
                    idle_durations[i] = 0
                else:
                    # accumulate
                    idle_durations[i] += round(real_interval)

            print_summary(rates)

            # check durations
            idle_gpus = [i for i, d in enumerate(idle_durations) if d >= duration * 60]  # second-minute conversion
            if len(idle_gpus) == 0:
                continue

            verbose(f'Found idle GPUs: {[rates[i]["index"] for i in idle_gpus]}')
            for idx in idle_gpus:
                # reset
                idle_durations[idx] = 0

            # send emails
            verbose('Sending alarm email...')
            connection = smtp_connect(config_dict)
            to = config_dict['to']
            mail = MIMEMultipart()
            mail['Subject'] = Header('GPU Idle Alarm', 'utf8').encode()
            mail['From'] = f'{connection.user} <{connection.user}>'
            mail['To'] = to
            content = (
                f'The following GPUs have been idle for more than {duration} minutes:\n'
                + '\n'.join(f'[{rates[idx]["index"]}] {device_names[idx]}' for idx in idle_gpus)
            )
            mail.attach(MIMEText(content, 'plain', 'utf8'))
            connection.sendmail(connection.user, to, mail.as_string())
            connection.quit()
            verbose(f'Email sent to {to} successfully.')

    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
