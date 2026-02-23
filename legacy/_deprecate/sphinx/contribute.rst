Contributing to the ontology
============================

There are two ways you can contribute to the ontology.

Suggest minor changes on existing elements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`Create a feature
request <https://github.com/emmo-repo/domain-battery/issues/new>`__ in a
`Github
Issue <https://docs.github.com/en/issues/tracking-your-work-with-issues/creating-an-issue>`__
to suggest edits to names, defintions, references on existing classes
and properties.

Propose additions/deletion of elements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

   **NOTE:** We recommend contacting some of the
   `BattINFO <https://github.com/BIG-MAP/BattINFO>`__ contributors in
   advance to discuss which additions and/or deletions you wish to make.

We recommend using the `forking
workflow <https://www.atlassian.com/git/tutorials/comparing-workflows/forking-workflow>`__
to contribute additions/deletions. Fork this repository, clone the fork
on your local PC, create your branch based on the existing ``dev``
branch (e.g. ``dev_john_doe``) and work on the editions in you local
copy.

You can edit ontologes in two main ways. One is programmatically, using
for instance `EMMOntoPy <https://github.com/emmo-repo/EMMOntoPy>`__. The
second and more common is using the interface provided by the Protégé
software. In case of the latter, `install
Protégé <https://protege.stanford.edu/>`__ and use it to open the
ontology file you wish to edit. Before adding elements, ensure Prot´égé
is configured to create IRIs in the right format:

-  Open Protégé
-  Go to File/Open and load the ontology file you wish to modify
-  Go to File/Preferences and there go to the New Entities Tab
-  Ensure you have configured the preferences as shown below:

   | |Protege config.|
   | Here is the “Specified IRI” for you to copy:
     ``https://emmo.info/battery#``

-  Once you have made your changes, commit them to your fork and `create
   a pull
   request <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request>`__.
-  We will merge the request after assessing it.

.. |Protege config.| image:: doc/img/protege_config_contribute.png

