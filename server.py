#!/usr/bin/env python3
"""Simple server for comparing 3DGS experiment renders side-by-side."""

import os
import re
import threading
import time
from flask import Flask, jsonify, render_template, request, send_file


def _natural_key(s: str):
    """Split string into [text, number, text, number, ...] for natural sorting."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

app = Flask(__name__)

# The viewer repeatedly asks for the same directory information while the user
# switches images.  A short cache prevents unnecessary directory scans without
# making newly written renders take long to appear.
_CACHE_TTL_SECONDS = 5
_cache = {}
_cache_lock = threading.Lock()


def _get_cached(key, loader):
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    value = loader()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _subdirectories(path: str):
    """Return direct subdirectory names in a stable, natural order."""
    with os.scandir(path) as entries:
        return tuple(sorted(
            (entry.name for entry in entries if entry.is_dir()),
            key=_natural_key,
        ))


def _experiment_directories(base_path: str):
    names = _get_cached(
        ('experiments', base_path),
        lambda: _subdirectories(base_path),
    )
    return [{'name': name, 'path': os.path.join(base_path, name)} for name in names]


def _iteration_dir(exp_path: str, subset: str):
    names = _get_cached(
        ('iterations', exp_path, subset),
        lambda: _subdirectories(os.path.join(exp_path, subset)),
    )
    return names[0] if names else None


def _image_metadata(exp_path: str, subset: str):
    """Read the chosen iteration and its available render image indices."""
    def load():
        iter_dir = _iteration_dir(exp_path, subset)
        if not iter_dir:
            return (), None, False, False

        iter_path = os.path.join(exp_path, subset, iter_dir)
        renders_path = os.path.join(iter_path, 'renders')
        try:
            with os.scandir(renders_path) as entries:
                filenames = tuple(sorted(
                    (entry.name for entry in entries
                     if entry.is_file() and entry.name.lower().endswith(('.png', '.jpg', '.jpeg'))),
                    key=_natural_key,
                ))
        except FileNotFoundError:
            filenames = ()

        return (
            tuple(os.path.splitext(name)[0] for name in filenames),
            iter_dir,
            os.path.isdir(os.path.join(iter_path, 'gt')),
            os.path.isdir(os.path.join(iter_path, 'regions')),
        )

    return _get_cached(('image_metadata', exp_path, subset), load)


@app.route('/')
def index():
    return render_template('index.html', default_path=app.config.get('DEFAULT_PATH', ''))


@app.route('/api/experiments')
def api_experiments():
    """List subdirectories under the given base path."""
    base_path = request.args.get('path', '')
    if not base_path or not os.path.isdir(base_path):
        return jsonify({'error': 'Invalid or missing path', 'experiments': []})

    try:
        experiments = _experiment_directories(base_path)
    except OSError as exc:
        return jsonify({'error': f'Unable to read path: {exc.strerror or exc}', 'experiments': []})

    return jsonify({'experiments': experiments, 'error': None})


@app.route('/api/image_indices')
def api_image_indices():
    """List available image indices for a given experiment and subset (test/train)."""
    exp_path = request.args.get('exp_path', '')
    subset = request.args.get('subset', 'test')

    subset_path = os.path.join(exp_path, subset)
    if not os.path.isdir(subset_path):
        return jsonify({'error': f'Subset folder not found: {subset_path}', 'indices': []})

    try:
        indices, iter_dir, has_gt, has_regions = _image_metadata(exp_path, subset)
    except OSError as exc:
        return jsonify({'error': f'Unable to read images: {exc.strerror or exc}', 'indices': []})

    if not iter_dir:
        return jsonify({'error': 'No iteration folders found', 'indices': []})

    return jsonify({
        'indices': list(indices),
        'iter_dir': iter_dir,
        'has_gt': has_gt,
        'has_regions': has_regions,
        'error': None,
    })


@app.route('/image')
def serve_image():
    """Serve a rendered or GT image file."""
    exp_path = request.args.get('exp_path', '')
    subset = request.args.get('subset', 'test')
    img_type = request.args.get('type', 'render')
    img_idx = request.args.get('idx', '0')

    subset_path = os.path.join(exp_path, subset)
    if not os.path.isdir(subset_path):
        return 'Subset not found', 404

    try:
        iter_dir = _iteration_dir(exp_path, subset)
    except OSError:
        return 'Unable to read iteration folders', 503
    if not iter_dir:
        return 'No iteration folders', 404

    if img_type == 'gt':
        subfolder = 'gt'
    elif img_type == 'region':
        subfolder = 'regions'
    else:
        subfolder = 'renders'
    img_dir = os.path.join(subset_path, iter_dir, subfolder)
    if not os.path.isdir(img_dir):
        return 'Image folder not found', 404

    for ext in ('.png', '.jpg', '.jpeg'):
        img_path = os.path.join(img_dir, f'{img_idx}{ext}')
        if os.path.isfile(img_path):
            return send_file(img_path)
    return 'Image not found', 404


def main():
    import argparse
    parser = argparse.ArgumentParser(description='3DGS Experiment Viewer Server')
    parser.add_argument('--port', type=int, default=8765, help='Server port')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Server host')
    parser.add_argument('--path', type=str, default='',
                        help='Default base path for experiments')
    parser.add_argument('--debug', action='store_true',
                        help='Enable Flask debug mode and auto-reload')
    args = parser.parse_args()

    app.config['DEFAULT_PATH'] = args.path
    print(f'\n  GS Viewer: http://localhost:{args.port}\n')
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == '__main__':
    main()
