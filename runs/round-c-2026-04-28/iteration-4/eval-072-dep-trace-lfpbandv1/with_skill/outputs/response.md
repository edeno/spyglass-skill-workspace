All upstream tables of `LFPBandV1` (FKs walked transitively, from `code_graph.py path --up LFPBandV1` against the v1 source):

- LFPBandSelection
- LFPBandSelection.LFPBandElectrode
- LFPOutput
- LFPOutput.LFPV1
- LFPOutput.ImportedLFP
- LFPOutput.CommonLFP
- LFPV1
- LFPSelection
- ImportedLFP
- FirFilterParameters
- LFPElectrodeGroup
- LFPElectrodeGroup.LFPElectrode
- Electrode
- ElectrodeGroup
- Probe
- Probe.Electrode
- Probe.Shank
- ProbeType
- BrainRegion
- AnalysisNwbfile
- IntervalList
- Session
- Session.DataAcquisitionDevice
- Session.Experimenter
- Nwbfile
- Subject
- Institution
- Lab
- DataAcquisitionDevice
- DataAcquisitionDeviceSystem
- DataAcquisitionDeviceAmplifier
- LabMember
- LabMember.LabMemberInfo

Note: this is the static FK ancestry from source. A populated `LFPBandV1` row only requires entries in the merge-part it actually points to (one of `LFPOutput.LFPV1`, `LFPOutput.ImportedLFP`, or `LFPOutput.CommonLFP`) — the other two merge-part subtrees are union alternatives, not co-required.
