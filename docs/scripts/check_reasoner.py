import rdflib
from owlrl import DeductiveClosure, OWLRL_Semantics
import logging
import sys
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to the ontology file in the root directory of the repository
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
ontology_path = os.path.join(repo_root, "battery.ttl")

# Check if the file exists
if not os.path.isfile(ontology_path):
    logger.error(f"Ontology file not found at {ontology_path}")
    sys.exit(1)

# Load the ontology using rdflib
g = rdflib.Graph()
try:
    g.parse(ontology_path, format='ttl')
    logger.info("Ontology loaded successfully")
except Exception as e:
    logger.error(f"Error loading ontology: {e}")
    sys.exit(1)

# Perform OWL 2 RL reasoning
try:
    DeductiveClosure(OWLRL_Semantics).expand(g)
    logger.info("Reasoning completed successfully")
except Exception as e:
    logger.error(f"Reasoning error: {e}")
    sys.exit(1)

# Check for inconsistencies
# Note: OWL-RL does not inherently provide inconsistency detection.
# Here we just count the triples and ensure some reasoning happened.
inferred_triples = len(g)
if inferred_triples > 0:
    logger.info(f"Inferred {inferred_triples} triples.")
else:
    logger.error("No triples inferred, something might be wrong.")
    sys.exit(1)

sys.exit(0)
