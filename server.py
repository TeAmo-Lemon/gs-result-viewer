#!/usr/bin/env python3
"""Simple server for comparing 3DGS experiment renders side-by-side."""

import os
import re
from flask import Flask, jsonify, render_template, request, send_file


def _natural_key(s: str):
    """Split string into [text, number, text, number, ...] for natural sorting."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html', default_path=app.config.get('DEFAULT_PATH', ''))


@app.route('/api/experiments')
def api_experiments():
    """List subdirectories under the given base path."""
    base_path = request.args.get('path', '')
    if not base_path or not os.path.isdir(base_path):
        return jsonify({'error': 'Invalid or missing path', 'experiments': []})

    experiments = []
    try:
        for name in sorted(os.listdir(base_path), key=_natural_key):
            full = os.path.join(base_path, name)
            if not os.path.isdir(full):
                continue
            experiments.append({
                'name': name,
                'path': full,
            })
    except PermissionError:
        return jsonify({'error': 'Permission denied', 'experiments': []})

    return jsonify({'experiments': experiments, 'error': None})


@app.route('/api/image_indices')
def api_image_indices():
    """List available image indices for a given experiment and subset (test/train)."""
    exp_path = request.args.get('exp_path', '')
    subset = request.args.get('subset', 'test')

    subset_path = os.path.join(exp_path, subset)
    if not os.path.isdir(subset_path):
        return jsonify({'error': f'Subset folder not found: {subset_path}', 'indices': []})

    # Must contain at least one subdir (e.g. ours_1500)
    iter_dirs = [d for d in os.listdir(subset_path)
                 if os.path.isdir(os.path.join(subset_path, d))]
    if not iter_dirs:
        return jsonify({'error': 'No iteration folders found', 'indices': []})

    iter_dir = iter_dirs[0]
    renders_path = os.path.join(subset_path, iter_dir, 'renders')
    gt_path = os.path.join(subset_path, iter_dir, 'gt')
    regions_path = os.path.join(subset_path, iter_dir, 'regions')

    indices = []
    if os.path.isdir(renders_path):
        for fname in sorted(os.listdir(renders_path), key=_natural_key):
            if fname.endswith('.png') or fname.endswith('.jpg') or fname.endswith('.jpeg'):
                indices.append(os.path.splitext(fname)[0])

    return jsonify({
        'indices': indices,
        'iter_dir': iter_dir,
        'has_gt': os.path.isdir(gt_path),
        'has_regions': os.path.isdir(regions_path),
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

    iter_dirs = [d for d in os.listdir(subset_path)
                 if os.path.isdir(os.path.join(subset_path, d))]
    if not iter_dirs:
        return 'No iteration folders', 404

    iter_dir = iter_dirs[0]
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
            return send_file(img_path, mimetype='image/png')
    return 'Image not found', 404


def main():
    import argparse
    parser = argparse.ArgumentParser(description='3DGS Experiment Viewer Server')
    parser.add_argument('--port', type=int, default=8765, help='Server port')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Server host')
    parser.add_argument('--path', type=str, default='',
                        help='Default base path for experiments')
    args = parser.parse_args()

    app.config['DEFAULT_PATH'] = args.path
    print(f'\n  GS Viewer: http://localhost:{args.port}\n')
    app.run(host=args.host, port=args.port, debug=True)


if __name__ == '__main__':
    main()
