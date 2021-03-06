"""Mock endpoint for classifier service."""
from flask import Flask, jsonify

application = Flask(__name__)


@application.route('/status', methods=['GET'])
def get_status():
    """Return classifier status."""
    return 'ok'


@application.route('/classifier/', methods=['POST'])
def classify():
    """Generate classification results."""
    return jsonify({
        "classifier": [
            {
                "category": "physics.comp-ph",
                "logodds": -0.11,
                "topwords": [
                    {"processors": 13},
                    {"fft": 13},
                    {"decyk": 4},
                    {"fast fourier transform": 7},
                    {"parallel": 10}
                ]
            },
            {
                "category": "cs.MS",
                "logodds": -0.14,
                "topwords": [
                    {"fft": 13},
                    {"processors": 13},
                    {"fast fourier transform": 7},
                    {"parallel": 10},
                    {"processor": 7}
                ]
            },
            {
                "category": "math.NA",
                "logodds": -0.16,
                "topwords": [
                    {"fft": 13},
                    {"fast fourier transform": 7},
                    {"algorithm": 6},
                    {"ux": 4},
                    {"multiplications": 5}
                ]
            }
        ],
        "counts": {
            "chars": 15107,
            "pages": 12,
            "stops": 804,
            "words": 2860
        },
        "flags": {}
    })
