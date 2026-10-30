import React from 'react';
import { ModePage } from '../../components/ModePage';
import { CODE_MODE_CASES, ModeScreenProps } from './modeCases';

export const CodeMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="code" customCases={CODE_MODE_CASES} {...props} />;
};
