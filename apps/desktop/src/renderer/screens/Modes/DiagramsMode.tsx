import React from 'react';
import { ModePage } from '../../components/ModePage';
import { DIAGRAMS_MODE_CASES, ModeScreenProps } from './modeCases';

export const DiagramsMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="diagrams" customCases={DIAGRAMS_MODE_CASES} {...props} />;
};
