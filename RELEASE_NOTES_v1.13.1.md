# Lotly v1.13.1

## Fix
- Fixed Streamlit `StreamlitWidgetAlreadyInstantiatedError` when opening Deal Room from Discover, Pipeline or Deal Room index.
- Programmatic page changes are now queued through `_lotly_pending_page` and applied before the sidebar navigation widget is instantiated on the next rerun.
- Discover visual design remains locked.
