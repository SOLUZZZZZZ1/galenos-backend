MULTIPROFILE (enum + switch + endpoint unificado)

Añade:
- ui_profiles.py
- overlay_dispatcher.py
- imaging.py actualizado con POST /imaging/overlay/{imaging_id}

Ejemplo:
POST /imaging/overlay/53
Body: {"profile":"MSK"}

Nota: guarda en msk_overlay_json por compatibilidad (luego haremos overlay_json común).
