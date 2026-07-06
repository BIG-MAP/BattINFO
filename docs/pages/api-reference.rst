Python API reference
====================

The curated core of the Python surface, generated from the source docstrings
and field descriptions — it cannot drift from the code. The narrative tour
lives in :doc:`../python-api`; the authoring workspace has its own page at
:doc:`../workspace-authoring`.

Authoring models
----------------

The five record models are both the canonical source of truth and the
authoring input: construct them with the flat field names you know from the
datasheet and hand them to ``publish`` or the matching ``save_*`` function.

.. autopydantic_model:: battinfo.CellSpecification
   :members: false

.. autopydantic_model:: battinfo.CellInstance
   :members: false

.. autopydantic_model:: battinfo.TestSpec
   :members: false

.. autopydantic_model:: battinfo.Test
   :members: false

.. autopydantic_model:: battinfo.Dataset
   :members: false

.. autopydantic_model:: battinfo.ProvenanceInfo
   :members: false

Publish and save
----------------

.. autofunction:: battinfo.publish

.. autofunction:: battinfo.save_record

.. autofunction:: battinfo.bulk_save_session

Query and validate
------------------

.. autofunction:: battinfo.query_cell_specs

.. autofunction:: battinfo.validate_record_report

.. autofunction:: battinfo.record_to_jsonld

Workspaces
----------

.. autoclass:: battinfo.AuthoringWorkspace
   :no-members:

.. autoclass:: battinfo.Workspace
   :no-members:

Every method of the authoring workspace is documented in
:doc:`../workspace-authoring`; run ``ws.commands()`` for the live cheat sheet.
