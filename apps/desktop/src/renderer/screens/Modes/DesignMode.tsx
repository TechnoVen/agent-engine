import React from 'react';
import { ModePage } from '../../components/ModePage';
import { DESIGN_MODE_CASES, ModeScreenProps } from './modeCases';

export const DesignMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="design" customCases={DESIGN_MODE_CASES} {...props} />;
};
