A dataset record describes measured data files — where they live
(`access_url`, distributions with checksums), what they measure
(`variable_measured`, techniques), and what they are about (`about` links to
the cell and the test that produced them). The files themselves stay wherever
they are published (Zenodo, an institutional store); the record is the
semantic layer over them.

A dataset **series** is the collection those datasets belong to — one record
for a whole deposit or study. There is no separate record type: a series is
an ordinary dataset flavored by `additional_type: ["DatasetSeries"]` (DCAT 3
declares `dcat:DatasetSeries` a subclass of `dcat:Dataset`). Membership is
stated on each member through `series_id`, which emits as `dcat:inSeries`
and `schema:isPartOf`. Because members carry the forward edge, the collection
publishes first. A series record carries no cell link of its own — its
members do — and the strict validation policy admits that for the series
flavor only.
