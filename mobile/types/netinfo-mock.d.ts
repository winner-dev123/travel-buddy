// The package ships its Jest mock without type declarations.
declare module '@react-native-community/netinfo/jest/netinfo-mock.js' {
  const netInfoMock: Record<string, unknown>;
  export default netInfoMock;
}
