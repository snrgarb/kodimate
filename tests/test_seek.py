# -*- coding: utf-8 -*-
import json

from kodimate import seek


def test_seek_stepper_accumulates_through_defined_steps():
    stepper = seek.SeekStepper(seek.DEFAULT_STEPS)

    assert stepper.press(-1) == -10
    assert stepper.press(-1) == -30
    assert stepper.press(-1) == -60


def test_seek_stepper_caps_at_largest_step():
    stepper = seek.SeekStepper([-30, -10, 10, 30])

    stepper.press(-1)
    stepper.press(-1)
    assert stepper.press(-1) == -30


def test_seek_stepper_opposite_press_backs_off():
    stepper = seek.SeekStepper(seek.DEFAULT_STEPS)
    stepper.press(-1)
    stepper.press(-1)  # -30

    assert stepper.press(1) == -10


def test_seek_stepper_backing_off_to_zero_cancels():
    stepper = seek.SeekStepper(seek.DEFAULT_STEPS)
    stepper.press(-1)  # -10

    assert stepper.press(1) == 0


def test_seek_stepper_press_largest_jumps_straight_to_cap():
    stepper = seek.SeekStepper(seek.DEFAULT_STEPS)

    assert stepper.press_largest(-1) == -600
    assert stepper.press_largest(1) == 600


def test_seek_stepper_reset_clears_pending():
    stepper = seek.SeekStepper(seek.DEFAULT_STEPS)
    stepper.press(-1)

    stepper.reset()

    assert stepper.pending == 0


def test_format_step_seconds_and_minutes():
    assert seek.format_step(0) == ''
    assert seek.format_step(-10) == '-10s'
    assert seek.format_step(30) == '+30s'
    assert seek.format_step(-60) == '-1m'
    assert seek.format_step(600) == '+10m'


def test_read_seek_settings_defaults_on_failure():
    def execute_jsonrpc(request):
        raise RuntimeError('boom')

    steps, delay_ms = seek.read_seek_settings(execute_jsonrpc)

    assert steps == seek.DEFAULT_STEPS
    assert delay_ms == seek.DEFAULT_DELAY_MS


def test_read_seek_settings_reads_values_from_jsonrpc():
    def execute_jsonrpc(request):
        payload = json.loads(request)
        setting = payload['params']['setting']
        value = [-20, -10, 10, 20] if setting == 'videoplayer.seeksteps' else 500
        return json.dumps({'id': 1, 'jsonrpc': '2.0', 'result': {'value': value}})

    steps, delay_ms = seek.read_seek_settings(execute_jsonrpc)

    assert steps == [-20, -10, 10, 20]
    assert delay_ms == 500
