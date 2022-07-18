import store from "../store";

const FETCH_CIRCULARS_OK = "skyportal/FETCH_CIRCULARS_OK";

// eslint-disable-next-line import/prefer-default-export
export function fetchGcnEventCirculars(gcnSubject) { 
  // gcnSubject is date code i.e. 220630A
  return {
    type: FETCH_CIRCULARS_OK,
  };
}

const reducer = (state = null, action) => {
  switch (action.type) {
    case FETCH_CIRCULARS_OK: {
      return {
        ...state,
        gcnEventCirculars: action.data,
      };
    }
    default:
      return state;
  }
};

store.injectReducer("circulars", reducer);
