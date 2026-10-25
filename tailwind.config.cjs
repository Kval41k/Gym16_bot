module.exports = {
  ...{
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            ios: {
              blue: '#007AFF',
              green: '#34C759',
              red: '#FF3B30',
              orange: '#FF9500',
              yellow: '#FFCC00',
              teal: '#5AC8FA',
              indigo: '#5856D6',
              bgLight: '#F2F2F7',
              cardLight: '#FFFFFF',
              bgDark: '#000000',
              cardDark: '#1C1C1E',
              cardDark2: '#2C2C2E',
              separatorLight: '#C6C6C8',
              separatorDark: '#38383A',
              secondaryText: '#8E8E93'
            }
          },
          boxShadow: {
            'ios-sm': '0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02)',
            'ios-card': '0 4px 16px rgba(0, 0, 0, 0.05), 0 1px 3px rgba(0, 0, 0, 0.02)',
            'ios-sheet': '0 -4px 24px rgba(0, 0, 0, 0.12)'
          }
        }
      }
    },
  content: ['./static/index.html', './static/*.js']
};
