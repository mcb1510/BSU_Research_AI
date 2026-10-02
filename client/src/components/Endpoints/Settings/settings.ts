import { EModelEndpoint } from 'librechat-data-provider';
import type { FC } from 'react';
import type { TModelSelectProps } from '~/common';
import OpenAISettings from './OpenAI';

const settings: { [key: string]: FC<TModelSelectProps> | undefined } = {
  [EModelEndpoint.agents]: OpenAISettings,
  [EModelEndpoint.openAI]: OpenAISettings,
  [EModelEndpoint.custom]: OpenAISettings,
  [EModelEndpoint.azureOpenAI]: OpenAISettings,
};

const multiViewSettings: {
  [key: string]: FC<Omit<TModelSelectProps, 'setOption'>> | undefined;
} = {};

export const getSettings = () => {
  return {
    settings,
    multiViewSettings,
  };
};
