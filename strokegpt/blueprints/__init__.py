from .audio import audio_blueprint
from .modes import modes_blueprint
from .motion import motion_blueprint
from .settings import settings_blueprint


def register_blueprints(app):
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(motion_blueprint)
    app.register_blueprint(audio_blueprint)
    app.register_blueprint(modes_blueprint)
