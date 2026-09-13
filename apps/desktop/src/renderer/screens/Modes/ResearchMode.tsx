import React from 'react';
import { ModePage } from '../../components/ModePage';
import { RESEARCH_MODE_CASES, ModeScreenProps } from './modeCases';

export const ResearchMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="deep-research" customCases={RESEARCH_MODE_CASES} {...props} />;
};
