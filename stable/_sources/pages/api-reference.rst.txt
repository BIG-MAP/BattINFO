Python API
==========

.. include:: ../python-api.md
   :parser: myst_parser.sphinx_

Generated reference
-------------------

Everything below is generated from the source docstrings and field
descriptions — it cannot drift from the code. The authoring workspace has its
own page at :doc:`../workspace-authoring`.

The record classes
~~~~~~~~~~~~~~~~~~

The five record classes (``CellSpec``, ``Cell``, ``TestSpec``, ``Test`` and
``Dataset``) are the authoring input: construct them with the flat field
names you know from the datasheet, then save each with its ``save_*``
function (``save_cell_spec``, ``save_cell_instance``, ``save_test_spec``,
``save_test`` or ``save_dataset``). ``publish`` is a shortcut for a
``CellSpec`` only. ``ProvenanceInfo``, documented with them, is the
provenance block every record embeds. Every field is documented below; quantity keys and unit
symbols are enumerated in :doc:`property-reference`.

.. autopydantic_model:: battinfo.CellSpec
   :members:
   :model-show-field-summary: True

.. autopydantic_model:: battinfo.Cell
   :members:
   :model-show-field-summary: True

.. autopydantic_model:: battinfo.TestSpec
   :members:
   :model-show-field-summary: True

.. autopydantic_model:: battinfo.Test
   :members:
   :model-show-field-summary: True

.. autopydantic_model:: battinfo.Dataset
   :members:
   :model-show-field-summary: True

.. autopydantic_model:: battinfo.ProvenanceInfo
   :members:
   :model-show-field-summary: True

Publish and save
~~~~~~~~~~~~~~~~

.. autofunction:: battinfo.publish

.. autofunction:: battinfo.save_cell_spec

.. autofunction:: battinfo.save_cell_instance

.. autofunction:: battinfo.save_test_spec

.. autofunction:: battinfo.save_test

.. autofunction:: battinfo.save_dataset

.. autofunction:: battinfo.save_record

.. autofunction:: battinfo.bulk_save_session

Query and validate
~~~~~~~~~~~~~~~~~~

.. autofunction:: battinfo.query_cell_specs

.. autofunction:: battinfo.validate_record_report

.. autofunction:: battinfo.record_to_jsonld

Record titles and handles
~~~~~~~~~~~~~~~~~~~~~~~~~

``battinfo.naming`` builds a record's title (its ``name``) and its handle, the
short slug a registry workspace shows as ``<workspace>/<handle>``, from
structured parts. The how-to is :doc:`../howto/name-your-records`.

.. autofunction:: battinfo.naming.handle_for

.. autofunction:: battinfo.naming.title_for

.. autofunction:: battinfo.naming.is_valid_handle

.. autofunction:: battinfo.naming.kind_word

The workspace object
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: battinfo.AuthoringWorkspace
   :no-members:

Every method is documented in :doc:`../workspace-authoring`; run
``ws.commands()`` for the live cheat sheet. (The internal object-graph engine
in ``battinfo._workspace`` is an implementation detail — the deprecated
top-level ``Workspace`` name points you back here.)
