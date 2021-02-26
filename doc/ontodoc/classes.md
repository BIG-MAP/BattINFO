%%
%% This is Markdown file, except of lines starting with %% will
%% be stripped off.
%%


%HEADER "Generic concepts"    level=1
These classes are intended to be merged back into EMMO.

%HEADER "Participant subclasses"    level=2
%ENTITY ActiveParticipant
%ENTITY FunctionalMaterial

%HEADER "Process subclasses"    level=2
%ENTITY FunctionalProcess
%ENTITY ChemicalPhenomenon
%ENTITY ChemicalReaction

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

%HEADER "Additional quantity dimensions"    level=2
%ENTITY PerTemperatureDimension


%HEADER "Electrochemical and battery-specific concepts"    level=1

%% %BRANCHDOC ActiveParticipant ontologies=generic-concepts
%BRANCHDOC ActiveParticipant
%BRANCHDOC ElectrochemicalSystem
%BRANCHDOC ElectrochemicalCell
%BRANCHDOC ElectrochemicalComponent
%BRANCHDOC ElectrochemicalSubcomponent
%BRANCHDOC ElectrochemicalMaterial


%BRANCHDOC ElectrochemicalQuantity
%BRANCHDOC ElectrochemicalKineticQuantity
%BRANCHDOC ElectrochemicalThermodynamicQuantity
