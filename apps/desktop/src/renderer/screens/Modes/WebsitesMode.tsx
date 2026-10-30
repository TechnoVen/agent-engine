import React from 'react';
import { ModePage } from '../../components/ModePage';
import { WEBSITES_MODE_CASES, ModeScreenProps } from './modeCases';

export const WebsitesMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="websites" customCases={WEBSITES_MODE_CASES} {...props} />;
};
