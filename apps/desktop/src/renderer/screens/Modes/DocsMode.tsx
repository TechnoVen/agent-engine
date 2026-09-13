import React from 'react';
import { ModePage } from '../../components/ModePage';
import { DOCS_MODE_CASES, ModeScreenProps } from './modeCases';

export const DocsMode: React.FC<ModeScreenProps> = (props) => {
  return <ModePage mode="docs" customCases={DOCS_MODE_CASES} {...props} />;
};
