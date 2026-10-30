import React from 'react';
import { ModePage } from '../../components/ModePage';
import { SHEETS_MODE_CASES, ModeScreenProps } from './modeCases';

export const SheetsMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="sheets" customCases={SHEETS_MODE_CASES} {...props} />;
};
