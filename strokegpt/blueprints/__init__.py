from .audio import audio_blueprint
from .handy_bluetooth import handy_bluetooth_blueprint
from .modes import modes_blueprint
from .motion import motion_blueprint
from .settings import settings_blueprint
from .voice_input import voice_input_blueprint


def register_blueprints(app):
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(motion_blueprint)
    app.register_blueprint(audio_blueprint)
    app.register_blueprint(modes_blueprint)
    app.register_blueprint(voice_input_blueprint)
    app.register_blueprint(handy_bluetooth_blueprint)
