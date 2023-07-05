%%
%% This is Markdown file, except of lines starting with %% will
%% be stripped off.
%%


%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%HEADER "Generic concepts"    level=1

These classes are intended to be merged back into EMMO.

%HEADER "Process subclasses"    level=2
%ENTITY FunctionalProcess
%ENTITY ChemicalPhenomenon
%ENTITY ChemicalReaction

%HEADER "Participant subclasses"    level=2
%ENTITY ActiveParticipant
%ENTITY FunctionalMaterial

%HEADER "Physicalistic subclasses"    level=2
%ENTITY Pore

%HEADER "Physical quantities"    level=2
%ENTITY VolumetricThermalExpansionCoefficient
%ENTITY DiffusionCoefficient
%ENTITY SingleComponentDiffusivity
%ENTITY SingleComponentMaximalDiffusivity
%ENTITY SingleComponentActivationEnergyOfDiffusion
%ENTITY MolarHeatCapacity
%ENTITY EnergyDensity
%ENTITY ThermalExpansionCoefficient
%ENTITY HeatCapacity
%ENTITY ThermalConductivity
%ENTITY SpecificHeatCapacity

%HEADER "Physical dimensions"    level=2
%ENTITY PerTemperatureDimension


%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%HEADER "Electrochemical and battery-specific concepts"    level=1
All classes under here are defined with the https://big-map.github.io/BattINFO/ontology/BattINFO#
namespace.


%% %BRANCHDOC ActiveParticipant ontologies=generic-concepts
%BRANCHDOC ActiveParticipant
%BRANCHDOC ElectrochemicalSystem
%BRANCHDOC ElectrochemicalCell
%BRANCHDOC ElectrochemicalComponent
%BRANCHDOC ElectrochemicalSubcomponent
%BRANCHDOC ElectrochemicalMaterial


%BRANCHDOC ElectrochemicalQuantity
%BRANCHDOC ElectrochemicalTransportQuantity
%BRANCHDOC ElectrochemicalKineticQuantity
%BRANCHDOC ElectrochemicalThermodynamicQuantity
%BRANCHDOC ElectrochemicalConstant

%BRANCHDOC PhysicalQuantity namespaces=BattINFO title="Additional physical quantities" caption="Additional physical quantities defined in BattINFO.  Parent classes belonging to EMMO are shown in gray."


%BRANCHDOC MaterialRelation

%BRANCHDOC ChemicalSpecies namespaces=BattINFO


%HEADER "Real world objects"    level=2
%ENTITY ElectrodePore
%ENTITY ElectrochemicalDevice


%HEADER "Physical dimensions"    level=2
%ENTITY ChargePerMassDimension


%% %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%HEADER "Appendix"    level=1

%BRANCHFIG EMMO namespaces=BattINFO terminated=0 caption="All classes defined with the BattINFO namespace, except physical quantities.  In addition parent classes belonging to EMMO are shown in gray." leafs=PhysicalQuantity,PhysicalDimension

%BRANCHFIG PhysicalQuantity namespaces=BattINFO terminated=0 caption="All physical quantities defined with the BattINFO namespace.  In addition parent classes belonging to EMMO are shown in gray."
