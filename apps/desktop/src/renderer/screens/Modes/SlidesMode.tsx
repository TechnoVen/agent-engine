import React from 'react';
import { ModePage } from '../../components/ModePage';
import { SLIDES_MODE_CASES, ModeScreenProps } from './modeCases';

export const SlidesMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="slides" customCases={SLIDES_MODE_CASES} {...props} />;
};
