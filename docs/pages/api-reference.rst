Python API reference
====================

The curated core of the Python surface, generated from the source docstrings
and field descriptions — it cannot drift from the code. The narrative tour
lives in :doc:`../python-api`; the authoring workspace has its own page at
:doc:`../workspace-authoring`.

The record classes
------------------

The five record classes are both the canonical source of truth and the
authoring input: construct them with the flat field names you know from the
datasheet and hand them to ``publish`` or the matching ``save_*`` function.
Quantity keys and unit symbols are enumerated in :doc:`property-reference`.

.. autopydantic_model:: battinfo.CellSpec
   :members: false

.. autopydantic_model:: battinfo.Cell
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

The workspace
-------------

.. autoclass:: battinfo.AuthoringWorkspace
   :no-members:

Every method is documented in :doc:`../workspace-authoring`; run
``ws.commands()`` for the live cheat sheet. (The internal object-graph engine
in ``battinfo._workspace`` is an implementation detail — the deprecated
top-level ``Workspace`` name points you back here.)
