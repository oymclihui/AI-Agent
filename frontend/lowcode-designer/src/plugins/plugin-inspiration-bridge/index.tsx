import * as React from 'react';
import { IPublicEnumTransformStage, IPublicModelPluginContext } from '@alilc/lowcode-types';
import { Button, Message } from '@alifd/next';

export const INSPIRE_LCE_MSG = {
  READY: 'INSPIRE_LCE_READY',
  REQUEST_INIT: 'INSPIRE_LCE_REQUEST_INIT',
  INIT: 'INSPIRE_LCE_INIT',
  SAVE: 'INSPIRE_LCE_SAVE',
  SAVED_ACK: 'INSPIRE_LCE_SAVED_ACK',
} as const;

function getInspireId() {
  return new URLSearchParams(window.location.search).get('inspireId') || 'default';
}

const InspirationBridgePlugin = (ctx: IPublicModelPluginContext) => {
  return {
    async init() {
      const { project, skeleton } = ctx;
      const inspireId = getInspireId();
      const isEmbedded = window.parent !== window;

      const openPageSchema = (pageSchema: Record<string, unknown> | null | undefined) => {
        if (!pageSchema) {
          project.openDocument({ componentName: 'Page', fileName: 'inspiration', children: [] });
          return;
        }
        project.openDocument(pageSchema as never);
        project.simulatorHost?.rerender();
      };

      if (isEmbedded) {
        window.addEventListener('message', (ev) => {
          const data = ev.data;
          if (!data || typeof data !== 'object') return;
          if (data.type === INSPIRE_LCE_MSG.INIT && data.inspireId === inspireId) {
            openPageSchema(data.pageSchema);
          }
          if (data.type === INSPIRE_LCE_MSG.SAVED_ACK) {
            Message.success('已保存到灵感模板');
          }
        });

        window.parent.postMessage({ type: INSPIRE_LCE_MSG.REQUEST_INIT, inspireId }, '*');
      }

      skeleton.add({
        name: 'saveInspiration',
        area: 'topArea',
        type: 'Widget',
        props: { align: 'right' },
        content: (
          <Button
            type="primary"
            onClick={() => {
              const projectSchema = project.exportSchema(IPublicEnumTransformStage.Save);
              const pageSchema = project.getCurrentDocument()?.export(IPublicEnumTransformStage.Save);
              if (isEmbedded) {
                window.parent.postMessage(
                  {
                    type: INSPIRE_LCE_MSG.SAVE,
                    inspireId,
                    projectSchema,
                    pageSchema,
                  },
                  '*',
                );
              } else {
                localStorage.setItem(
                  `inspiration:lce:${inspireId}`,
                  JSON.stringify({ projectSchema, pageSchema }),
                );
                Message.success('已保存到 localStorage');
              }
            }}
          >
            保存到灵感
          </Button>
        ),
      });

      window.postMessage({ type: INSPIRE_LCE_MSG.READY, inspireId }, '*');
    },
  };
};

InspirationBridgePlugin.pluginName = 'InspirationBridgePlugin';
InspirationBridgePlugin.meta = {
  dependencies: ['EditorInitPlugin'],
};

export default InspirationBridgePlugin;
